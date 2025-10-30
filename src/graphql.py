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
# Extract referenced issues (#123 or repo#456 or org/repo#789)
# ----------------------------------------------------------------------------------------
def extract_referenced_issues_from_text(text):
    """Extracts issue references like #123 or repo#456 or org/repo#789."""
    pattern = r"(?:[\w\-]+\/[\w\-]+#\d+|[\w\-]+#\d+|#\d+)"
    return re.findall(pattern, text)


# ----------------------------------------------------------------------------------------
# Resolve issue reference (handles cross-repo issues too)
# ----------------------------------------------------------------------------------------
def resolve_issue_reference(reference):
    """Return issue ID, number, URL, org, and repo for a given reference."""
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
        }
      }
    }
    """
    variables = {"owner": org, "repo": repo, "number": number}
    response = requests.post(
        config.api_endpoint,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {config.gh_token}"},
    )
    data = response.json()
    issue = data.get("data", {}).get("repository", {}).get("issue")

    if issue:
        issue["org"] = org
        issue["repo"] = repo
    return issue


# ----------------------------------------------------------------------------------------
# Get issue state (OPEN or CLOSED)
# ----------------------------------------------------------------------------------------
def get_issue_state(issue_id, org, repo, issue_number):
    """
    Returns the current state of the issue: OPEN or CLOSED.
    Works reliably across cross-repo contexts.
    """
    # --- Try node query ---
    query_node = """
    query($issueId: ID!) {
      node(id: $issueId) {
        __typename
        ... on Issue {
          state
        }
      }
    }
    """
    try:
        response = requests.post(
            config.api_endpoint,
            json={"query": query_node, "variables": {"issueId": issue_id}},
            headers={"Authorization": f"Bearer {config.gh_token}"},
        )
        data = response.json()
        issue_node = data.get("data", {}).get("node", {})

        if issue_node and issue_node.get("__typename") == "Issue" and issue_node.get("state"):
            return issue_node["state"]

        # --- Fallback query using the resolved org/repo directly ---
        fallback_query = """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            issue(number: $number) {
              state
            }
          }
        }
        """
        variables = {"owner": org, "repo": repo, "number": issue_number}
        fallback_resp = requests.post(
            config.api_endpoint,
            json={"query": fallback_query, "variables": variables},
            headers={"Authorization": f"Bearer {config.gh_token}"},
        )
        fb_data = fallback_resp.json()
        issue_data = fb_data.get("data", {}).get("repository", {}).get("issue", {})
        if issue_data and issue_data.get("state"):
            return issue_data["state"]

        logging.error(f"Issue state not found for {org}/{repo}#{issue_number}")
        return None

    except Exception as e:
        logging.error(f"Error fetching issue state for {org}/{repo}#{issue_number}: {e}")
        return None
