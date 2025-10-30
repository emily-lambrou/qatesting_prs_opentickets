import logging
import requests
import re
import config

logging.basicConfig(level=logging.DEBUG)


# ----------------------------------------------------------------------------------------
# Fetch merged PRs into dev
# ----------------------------------------------------------------------------------------
def get_recent_merged_prs_in_dev(owner, repo):
    query = """
    query GetMergedPRs($owner: String!, $repo: String!, $afterCursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequests(
          first: 50
          after: $afterCursor
          baseRefName: "dev"
          states: MERGED
          orderBy: {field: UPDATED_AT, direction: DESC}
        ) {
          nodes {
            id
            number
            title
            bodyText
            mergedAt
            url
          }
          pageInfo {
            endCursor
            hasNextPage
          }
        }
      }
    }
    """
    variables = {"owner": owner, "repo": repo, "afterCursor": None}
    prs = []
    try:
        while True:
            response = requests.post(
                config.api_endpoint,
                json={"query": query, "variables": variables},
                headers={"Authorization": f"Bearer {config.gh_token}"},
            )
            data = response.json()
            if "errors" in data:
                logging.error(f"GraphQL query errors: {data['errors']}")
                break

            nodes = data.get("data", {}).get("repository", {}).get("pullRequests", {}).get("nodes", [])
            prs.extend(nodes)
            if not data["data"]["repository"]["pullRequests"]["pageInfo"]["hasNextPage"]:
                break
            variables["afterCursor"] = data["data"]["repository"]["pullRequests"]["pageInfo"]["endCursor"]

        return prs
    except requests.RequestException as e:
        logging.error(f"Request error: {e}")
        return []


# ----------------------------------------------------------------------------------------
# Extract referenced issues (#123 or repo#456 or org/repo#789) from PR description
# ----------------------------------------------------------------------------------------
def extract_referenced_issues_from_text(text):
    """Extracts issue references like #123 or repo#456 or org/repo#789."""
    pattern = r"(?:[\w\-]+\/[\w\-]+#\d+|[\w\-]+#\d+|#\d+)"
    return re.findall(pattern, text)


# ----------------------------------------------------------------------------------------
# Get issue state (OPEN or CLOSED)
# ----------------------------------------------------------------------------------------
def get_issue_state(org, repo, number):
    """Safely get the state (OPEN/CLOSED) of an issue."""
    query = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        issue(number: $number) {
          state
        }
      }
    }
    """
    variables = {"owner": org, "repo": repo, "number": number}
    try:
        response = requests.post(
            config.api_endpoint,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {config.gh_token}"},
        )
        data = response.json()
        issue = data.get("data", {}).get("repository", {}).get("issue", {})
        return issue.get("state")
    except Exception as e:
        logging.error(f"Error checking issue state for {org}/{repo}#{number}: {e}")
        return None


# ----------------------------------------------------------------------------------------
# Resolve issue reference (handles cross-repo issues too)
# ----------------------------------------------------------------------------------------
def resolve_issue_reference(reference):
    """Return issue ID, number, URL, and state for a given reference."""
    match = re.match(r"(?:(?P<org>[\w\-]+)/(?P<repo>[\w\-]+))?#(?P<number>\d+)", reference)
    if not match:
        return None

    org = match.group("org") or config.repository_owner
    repo = match.group("repo") or config.repository_name
    number = int(match.group("number"))

    query = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        issue(number: $number) {
          id
          number
          title
          url
          state
        }
      }
    }
    """
    variables = {"owner": org, "repo": repo, "number": number}
    try:
        response = requests.post(
            config.api_endpoint,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {config.gh_token}"},
        )
        data = response.json()
        issue = data.get("data", {}).get("repository", {}).get("issue")
        return issue
    except Exception as e:
        logging.error(f"Error resolving issue reference {reference}: {e}")
        return None


# ----------------------------------------------------------------------------------------
# Project and Status Handling
# ----------------------------------------------------------------------------------------
def get_project_id_by_title(owner, project_title):
    query = """
    query($owner: String!, $projectTitle: String!) {
      organization(login: $owner) {
        projectsV2(first: 10, query: $projectTitle) {
          nodes { id title }
        }
      }
    }
    """
    variables = {"owner": owner, "projectTitle": project_title}
    response = requests.post(
        config.api_endpoint,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {config.gh_token}"},
    )
    data = response.json()
    projects = data.get("data", {}).get("organization", {}).get("projectsV2", {}).get("nodes", [])
    for project in projects:
        if project["title"] == project_title:
            return project["id"]
    return None


def get_status_field_id(project_id, status_field_name):
    query = """
    query($projectId: ID!) {
      node(id: $projectId) {
        ... on ProjectV2 {
          fields(first: 100) {
            nodes {
              __typename
              ... on ProjectV2SingleSelectField {
                id
                name
              }
            }
          }
        }
      }
    }
    """
    response = requests.post(
        config.api_endpoint,
        json={"query": query, "variables": {"projectId": project_id}},
        headers={"Authorization": f"Bearer {config.gh_token}"},
    )
    data = response.json()
    fields = data.get("data", {}).get("node", {}).get("fields", {}).get("nodes", [])
    for field in fields:
        if field.get("__typename") == "ProjectV2SingleSelectField" and field.get("name") == status_field_name:
            return field["id"]
    logging.error(f"Status field '{status_field_name}' not found among project fields.")
    return None


def get_qatesting_status_option_id(project_id, status_field_name):
    query = """
    query($projectId: ID!) {
      node(id: $projectId) {
        ... on ProjectV2 {
          fields(first: 100) {
            nodes {
              __typename
              ... on ProjectV2SingleSelectField {
                id
                name
                options {
                  id
                  name
                }
              }
            }
          }
        }
      }
    }
    """
    response = requests.post(
        config.api_endpoint,
        json={"query": query, "variables": {"projectId": project_id}},
        headers={"Authorization": f"Bearer {config.gh_token}"},
    )
    data = response.json()
    fields = data.get("data", {}).get("node", {}).get("fields", {}).get("nodes", [])
    for field in fields:
        if field.get("__typename") == "ProjectV2SingleSelectField" and field.get("name") == status_field_name:
            for option in field.get("options", []):
                if option.get("name") == "QA Testing":
                    return option["id"]
    logging.error(f"'QA Testing' option not found under field '{status_field_name}'.")
    return None


# ----------------------------------------------------------------------------------------
# Fetch Project Items 
# ----------------------------------------------------------------------------------------
def get_project_items(owner, owner_type, project_number, status_field_name):
    """
    Fetch all items from the project board to map issues to their ProjectV2 item IDs.
    """
    query = """
    query($owner: String!, $projectNumber: Int!, $afterCursor: String) {
      organization(login: $owner) {
        projectV2(number: $projectNumber) {
          items(first: 100, after: $afterCursor) {
            nodes {
              id
              content {
                ... on Issue {
                  id
                  number
                  title
                  url
                }
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
      }
    }
    """
    variables = {"owner": owner, "projectNumber": project_number, "afterCursor": None}
    items = []

    try:
        while True:
            response = requests.post(
                config.api_endpoint,
                json={"query": query, "variables": variables},
                headers={"Authorization": f"Bearer {config.gh_token}"},
            )
            data = response.json()

            if "errors" in data:
                logging.error(f"GraphQL query errors: {data['errors']}")
                break

            nodes = (
                data.get("data", {})
                .get("organization", {})
                .get("projectV2", {})
                .get("items", {})
                .get("nodes", [])
            )
            items.extend(nodes)

            page_info = (
                data.get("data", {})
                .get("organization", {})
                .get("projectV2", {})
                .get("items", {})
                .get("pageInfo", {})
            )

            if not page_info.get("hasNextPage"):
                break
            variables["afterCursor"] = page_info.get("endCursor")

        return items
    except requests.RequestException as e:
        logging.error(f"Request error while fetching project items: {e}")
        return []


# ----------------------------------------------------------------------------------------
# Issue utilities
# ----------------------------------------------------------------------------------------
def get_issue_status(issue_id, status_field_name):
    query = """
    query($issueId: ID!, $statusField: String!) {
      node(id: $issueId) {
        ... on Issue {
          projectItems(first: 10) {
            nodes {
              fieldValueByName(name: $statusField) {
                ... on ProjectV2ItemFieldSingleSelectValue {
                  name
                }
              }
            }
          }
        }
      }
    }
    """
    variables = {"issueId": issue_id, "statusField": status_field_name}
    response = requests.post(
        config.api_endpoint,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {config.gh_token}"},
    )
    data = response.json()
    try:
        nodes = data["data"]["node"]["projectItems"]["nodes"]
        for item in nodes:
            field = item.get("fieldValueByName")
            if field:
                return field.get("name")
        return None
    except Exception:
        return None


def update_issue_status_to_qa_testing(owner, project_title, project_id, status_field_id, item_id, status_option_id):
    mutation = """
    mutation UpdateIssueStatus($projectId: ID!, $itemId: ID!, $statusFieldId: ID!, $statusOptionId: String!) {
      updateProjectV2ItemFieldValue(input: {
        projectId: $projectId,
        itemId: $itemId,
        fieldId: $statusFieldId,
        value: { singleSelectOptionId: $statusOptionId }
      }) {
        projectV2Item { id }
      }
    }
    """
    variables = {
        "projectId": project_id,
        "itemId": item_id,
        "statusFieldId": status_field_id,
        "statusOptionId": status_option_id,
    }
    response = requests.post(
        config.api_endpoint,
        json={"query": mutation, "variables": variables},
        headers={"Authorization": f"Bearer {config.gh_token}"},
    )
    return response.json().get("data")


def get_issue_comments(issue_id):
    query = """
    query GetIssueComments($issueId: ID!, $afterCursor: String) {
      node(id: $issueId) {
        ... on Issue {
          comments(first: 100, after: $afterCursor) {
            nodes {
              body
              createdAt
            }
            pageInfo {
              endCursor
              hasNextPage
            }
          }
        }
      }
    }
    """
    variables = {"issueId": issue_id, "afterCursor": None}
    comments = []
    while True:
        response = requests.post(
            config.api_endpoint,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {config.gh_token}"},
        )
        data = response.json()
        nodes = data.get("data", {}).get("node", {}).get("comments", {}).get("nodes", [])
        comments.extend(nodes)
        page = data.get("data", {}).get("node", {}).get("comments", {}).get("pageInfo", {})
        if not page.get("hasNextPage"):
            break
        variables["afterCursor"] = page.get("endCursor")
    return comments


def add_issue_comment(issue_id, body: str):
    mutation = """
    mutation AddComment($subjectId: ID!, $body: String!) {
      addComment(input: {subjectId: $subjectId, body: $body}) {
        commentEdge {
          node { id body }
        }
      }
    }
    """
    variables = {"subjectId": issue_id, "body": body}
    response = requests.post(
        config.api_endpoint,
        json={"query": mutation, "variables": variables},
        headers={"Authorization": f"Bearer {config.gh_token}"},
    )
    return response.json().get("data")
