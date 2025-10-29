import logging
import requests
import re
import config

logging.basicConfig(level=logging.DEBUG)


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


def extract_referenced_issues_from_text(text):
    pattern = r"(?:[\w\-]+\/[\w\-]+#\d+|[\w\-]+#\d+|#\d+)"
    return re.findall(pattern, text)


def resolve_issue_reference(reference):
    """Resolve issue reference and include its state (OPEN or CLOSED)."""
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
    response = requests.post(
        config.api_endpoint,
        json={"query": query, "variables": {"owner": org, "repo": repo, "number": number}},
        headers={"Authorization": f"Bearer {config.gh_token}"},
    )
    data = response.json()
    return data.get("data", {}).get("repository", {}).get("issue")


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
    response = requests.post(
        config.api_endpoint,
        json={"query": query, "variables": {"owner": owner, "projectTitle": project_title}},
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
        if field.get("name") == status_field_name:
            return field["id"]
    return None


def get_qatesting_status_option_id(project_id, status_field_name):
    query = """
    query($projectId: ID!) {
      node(id: $projectId) {
        ... on ProjectV2 {
          fields(first: 100) {
            nodes {
              ... on ProjectV2SingleSelectField {
                id
                name
                options { id name }
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
        if field.get("name") == status_field_name:
            for option in field.get("options", []):
                if option.get("name") == "QA Testing":
                    return option["id"]
    return None


def get_open_project_issues(owner, owner_type, project_number, status_field_name):
    """Fetch only OPEN issues from a project board."""
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
                  state
                }
              }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
    }
    """
    variables = {"owner": owner, "projectNumber": project_number, "afterCursor": None}
    open_items = []
    while True:
        response = requests.post(
            config.api_endpoint,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {config.gh_token}"},
        )
        data = response.json()
        nodes = data.get("data", {}).get("organization", {}).get("projectV2", {}).get("items", {}).get("nodes", [])
        for node in nodes:
            if node.get("content") and node["content"].get("state") == "OPEN":
                open_items.append(node)
        page = data["data"]["organization"]["projectV2"]["items"]["pageInfo"]
        if not page["hasNextPage"]:
            break
        variables["afterCursor"] = page["endCursor"]
    return open_items


def get_issue_status(issue_id, status_field_name):
    query = """
    query($issueId: ID!, $statusField: String!) {
      node(id: $issueId) {
        ... on Issue {
          projectItems(first: 10) {
            nodes {
              fieldValueByName(name: $statusField) {
                ... on ProjectV2ItemFieldSingleSelectValue { name }
              }
            }
          }
        }
      }
    }
    """
    response = requests.post(
        config.api_endpoint,
        json={"query": query, "variables": {"issueId": issue_id, "statusField": status_field_name}},
        headers={"Authorization": f"Bearer {config.gh_token}"},
    )
    data = response.json()
    try:
        nodes = data["data"]["node"]["projectItems"]["nodes"]
        for item in nodes:
            field = item.get("fieldValueByName")
            if field:
                return field.get("name")
    except Exception:
        return None
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
    response = requests.post(
        config.api_endpoint,
        json={"query": mutation, "variables": {
            "projectId": project_id,
            "itemId": item_id,
            "statusFieldId": status_field_id,
            "statusOptionId": status_option_id,
        }},
        headers={"Authorization": f"Bearer {config.gh_token}"},
    )
    return response.json().get("data")


def get_issue_comments(issue_id):
    query = """
    query GetIssueComments($issueId: ID!, $afterCursor: String) {
      node(id: $issueId) {
        ... on Issue {
          comments(first: 100, after: $afterCursor) {
            nodes { body createdAt }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
    }
    """
    comments, cursor = [], None
    while True:
        response = requests.post(
            config.api_endpoint,
            json={"query": query, "variables": {"issueId": issue_id, "afterCursor": cursor}},
            headers={"Authorization": f"Bearer {config.gh_token}"},
        )
        data = response.json()
        node = data.get("data", {}).get("node", {}).get("comments", {})
        comments.extend(node.get("nodes", []))
        if not node.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = node["pageInfo"]["endCursor"]
    return comments


def add_issue_comment(issue_id, body: str):
    mutation = """
    mutation AddComment($subjectId: ID!, $body: String!) {
      addComment(input: {subjectId: $subjectId, body: $body}) {
        commentEdge { node { id body } }
      }
    }
    """
    response = requests.post(
        config.api_endpoint,
        json={"query": mutation, "variables": {"subjectId": issue_id, "body": body}},
        headers={"Authorization": f"Bearer {config.gh_token}"},
    )
    return response.json().get("data")
