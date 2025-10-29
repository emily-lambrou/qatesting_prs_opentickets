from logger import logger
import config
import graphql
import time


def check_comment_exists(issue_id, comment_text):
    """Check if the comment already exists on the issue."""
    comments = graphql.get_issue_comments(issue_id)
    for comment in comments:
        if comment_text in comment.get("body", ""):
            return True
    return False


def notify_change_status():
    logger.info("🔄 QA Testing workflow started.")
    merged_prs = graphql.get_recent_merged_prs_in_dev(
        owner=config.repository_owner,
        repo=config.repository_name
    )

    if not merged_prs:
        logger.info("No merged PRs found in dev.")
        return

    project_title = config.project_title
    project_id = graphql.get_project_id_by_title(config.repository_owner, project_title)
    if not project_id:
        logger.error(f"Project {project_title} not found.")
        return

    status_field_id = graphql.get_status_field_id(project_id, config.status_field_name)
    status_option_id = graphql.get_qatesting_status_option_id(project_id, config.status_field_name)

    logger.info("Processing merged PRs...")

    for pr in merged_prs:
        pr_number = pr["number"]
        pr_url = pr["url"]
        pr_title = pr["title"]

        logger.info(f"Checking PR #{pr_number} ({pr_title}) for referenced issues...")
        linked_issues = graphql.extract_referenced_issues_from_text(pr.get("bodyText", ""))

        if not linked_issues:
            logger.info(f"PR #{pr_number} has no referenced issues.")
            continue

        for issue_ref in linked_issues:
            issue_data = graphql.resolve_issue_reference(issue_ref)
            if not issue_data:
                logger.warning(f"Could not resolve issue reference '{issue_ref}'.")
                continue

            issue_id = issue_data["id"]
            issue_number = issue_data["number"]

            # ✅ Step 1: Verify issue state before any further action
            issue_state = graphql.get_issue_state(config.repository_owner, config.repository_name, issue_number)
            if issue_state != "OPEN":
                logger.info(f"Skipping issue #{issue_number} — it is {issue_state}.")
                # Make absolutely sure we don’t accidentally reuse data
                issue_id = None
                continue

            comment_text = f"Testing will be available in 15 minutes (triggered by [PR #{pr_number}]({pr_url}))"

            # ✅ Step 2: Check for duplicate comment
            if check_comment_exists(issue_id, comment_text):
                logger.info(f"Skipping issue #{issue_number} — comment already exists.")
                continue

            # ✅ Step 3: Double-check open state again before writing (safety net)
            confirm_state = graphql.get_issue_state(config.repository_owner, config.repository_name, issue_number)
            if confirm_state != "OPEN":
                logger.warning(f"Aborting update for issue #{issue_number} — now {confirm_state}.")
                continue

            current_status = graphql.get_issue_status(issue_id, config.status_field_name)

            if current_status != "QA Testing":
                logger.info(f"Updating issue #{issue_number} to QA Testing...")
                update_result = graphql.update_issue_status_to_qa_testing(
                    owner=config.repository_owner,
                    project_title=project_title,
                    project_id=project_id,
                    status_field_id=status_field_id,
                    item_id=issue_id,
                    status_option_id=status_option_id,
                )

                if update_result:
                    logger.info(f"✅ Successfully updated issue #{issue_number} to QA Testing.")
                    graphql.add_issue_comment(issue_id, comment_text)
                else:
                    logger.error(f"❌ Failed to update issue #{issue_number}.")
            else:
                logger.info(f"Issue #{issue_number} already in QA Testing — adding comment.")
                graphql.add_issue_comment(issue_id, comment_text)

            time.sleep(0.4)  # avoid GitHub rate limits


def main():
    logger.info("🚀 Starting QA Testing automation...")
    if config.dry_run:
        logger.info("⚙️ DRY RUN MODE ENABLED.")
    notify_change_status()


if __name__ == "__main__":
    main()
