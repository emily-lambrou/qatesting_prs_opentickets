from logger import logger
import logging
import config
import graphql


def check_comment_exists(issue_id, comment_text):
    """Check if the comment already exists on the issue."""
    comments = graphql.get_issue_comments(issue_id)
    for comment in comments:
        if comment_text in comment.get("body", ""):
            return True
    return False


def notify_change_status():
    logger.info("Fetching merged PRs into dev...")

    merged_prs = graphql.get_recent_merged_prs_in_dev(
        owner=config.repository_owner,
        repo=config.repository_name
    )

    if not merged_prs:
        logger.info("No merged PRs found in dev.")
        return

    # --- Project setup ---
    project_title = config.project_title
    project_id = graphql.get_project_id_by_title(config.repository_owner, project_title)
    if not project_id:
        logging.error(f"Project {project_title} not found.")
        return

    status_field_id = graphql.get_status_field_id(project_id, config.status_field_name)
    if not status_field_id:
        logging.error(f"Status field not found in project {project_title}")
        return

    status_option_id = graphql.get_qatesting_status_option_id(project_id, config.status_field_name)
    if not status_option_id:
        logging.error(f"'QA Testing' option not found in project {project_title}")
        return

    items = graphql.get_open_project_issues(
        owner=config.repository_owner,
        owner_type=config.repository_owner_type,
        project_number=config.project_number,
        status_field_name=config.status_field_name
    )

    # --- Iterate merged PRs ---
    for pr in merged_prs:
        pr_number = pr["number"]
        pr_url = pr["url"]
        pr_title = pr["title"]

        logger.info(f"Checking PR #{pr_number} ({pr_title}) for mentioned issues in description...")

        linked_issues = graphql.extract_referenced_issues_from_text(pr.get("bodyText", ""))
        if not linked_issues:
            continue

        for issue_ref in linked_issues:
            issue_data = graphql.resolve_issue_reference(issue_ref)
            if not issue_data:
                continue

            issue_id = issue_data["id"]
            issue_number = issue_data["number"]

            # 🧠 Real-time double check to skip closed issues
            issue_state = graphql.get_issue_state(issue_id)
            if issue_state != "OPEN":
                logger.info(f"Skipping issue #{issue_number} — it is CLOSED (live check).")
                continue

            comment_text = (
                f"Testing will be available in 15 minutes "
                f"(triggered by [PR #{pr_number}]({pr_url}))"
            )

            # Avoid duplicates
            if check_comment_exists(issue_id, comment_text):
                logger.info(f"Skipping issue #{issue_number} — comment already exists.")
                continue

            current_status = graphql.get_issue_status(issue_id, config.status_field_name)
            if current_status != "QA Testing":
                logger.info(f"Updating issue #{issue_number} to QA Testing.")

                item_found = False
                for item in items:
                    if item.get("content") and item["content"].get("id") == issue_id:
                        item_found = True
                        update_result = graphql.update_issue_status_to_qa_testing(
                            owner=config.repository_owner,
                            project_title=project_title,
                            project_id=project_id,
                            status_field_id=status_field_id,
                            item_id=item["id"],
                            status_option_id=status_option_id,
                        )
                        if update_result:
                            logger.info(f"✅ Updated issue #{issue_number} to QA Testing.")
                            graphql.add_issue_comment(issue_id, comment_text)
                        else:
                            logger.error(f"❌ Failed to update issue #{issue_number}.")
                        break

                if not item_found:
                    logger.warning(f"Issue #{issue_number} not found in project.")
            else:
                logger.info(f"Issue #{issue_number} already in QA Testing.")
                graphql.add_issue_comment(issue_id, comment_text)


def main():
    logger.info("🔄 Process started...")
    if config.dry_run:
        logger.info("DRY RUN MODE ON!")

    notify_change_status()


if __name__ == "__main__":
    main()
