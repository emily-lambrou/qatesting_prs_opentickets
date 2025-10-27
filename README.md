# Issue Project Status changes to "QA Testing" if a pull request is merged in the dev branch 

**Overview**

GitHub does not provide a built-in mechanism to update project statuses upon PR merges. This workflow solves that gap by:

Automatically updating the central GitHub Project status to "QA Testing" when a PR is merged into dev.

Ensuring that duplicate updates and comments are avoided for cleaner workflows.

Adding a comment the same time as changing the status.

# How It Works

- Detects merged pull requests into the dev branch.

- Identifies linked issues in the project.

If an issue is not in QA Testing, the workflow:

- Updates its status → QA Testing.

- Adds a comment: Testing will be available in 15 minutes (triggered by [PR #123](https://github.com/org/repo/pull/123))

If the issue is already in QA Testing, the workflow:

- Leaves the status unchanged.

- Adds a new comment for each new PR merged into dev.

- If a PR is merged into non-dev branches (e.g. master), no status change or comment is made.

- Open PRs (not merged) are ignored.

### Prerequisites

Before you can start using this GitHub Action, you'll need to ensure you have the following:

1. A GitHub repository where you want to enable this action.
2. A GitHub project board (name: Requests Product Backlog) with a custom status field added.
3. A "QA Testing" status option added in the Status field.
4. A Token (Classic) with permissions to repo:*, write: org, read: org, read:user, user:email, project.
5. Yaml workflow running in your repository: emily-lambrou/status_changes_to_qatesting

### Inputs

| Input                                | Description                                                                                      |
|--------------------------------------|--------------------------------------------------------------------------------------------------|
| `gh_token`                           | The GitHub Token                                                                                 |
| `project_number`                     | The project number                                                                               |                                                         
| `status_field_name` _(optional)_     | The status field name. The default is `Status`                                                   |         
| `enterprise_github` _(optional)_     | `True` if you are using enterprise github and false if not. Default is `False`                   |
| `repository_owner_type` _(optional)_ | The type of the repository owner (oragnization or user). Default is `user`                       |
| `dry_run` _(optional)_               | `True` if you want to enable dry-run mode. Default is `False`                                    |


### Examples

#### Status changes to "QA Testing" if PR is merged in the dev branch 

To update the status of an issue to QA Testing, you'll need to create a GitHub Actions workflow in your repository. Below is
an example of a workflow YAML file:

```yaml

name: Update status field to QA Testing if PR is merged

# Runs every minute
on:
  schedule:
    - cron: '* * * * *'
  workflow_dispatch:

jobs:
  update_status_merged_pr:
    runs-on: self-hosted
    
    env:
      ACTIONS_RUNNER_DEBUG: 'true'
      ACTIONS_STEP_DEBUG: 'true'
    

    steps:
      # Checkout the code to be used by runner
      - name: Checkout code
        uses: actions/checkout@v3

      - name: Check for merged PRs and change the status
        uses: emily-lambrou/qatesting_prs_opentickets@v1.0
        with:
          dry_run: ${{ vars.DRY_RUN }}           
          gh_token: ${{ secrets.GH_TOKEN }}      
          project_number: ${{ vars.PROJECT_NUMBER }} 
          project_title: 'Requests Product Backlog'
          enterprise_github: 'True'
          repository_owner_type: 'organization'
       
```
