"""
Deepnote Remote Execution Trigger

Triggers a notebook on Deepnote to run the sentiment pipeline in the cloud.
Use when:
  - Local machine is off/unreliable
  - Want cloud-based backup execution
  - Need Deepnote's compute for heavier analysis

Setup:
  1. Create a Deepnote project, add a notebook with pipeline code
  2. Get project_id and notebook_id from the notebook URL
  3. Set env vars: DEEPNOTE_API_KEY, DEEPNOTE_PROJECT_ID, DEEPNOTE_NOTEBOOK_ID

Usage:
    python deepnote_trigger.py                     # trigger execution
    python deepnote_trigger.py --check             # check if API key works
"""

import logging
import os
import sys

import requests

logger = logging.getLogger("deepnote")

DEEPNOTE_API_KEY = os.environ.get(
    "DEEPNOTE_API_KEY",
    "e2e2854fa9ce620426d2b2161c7bfc452890cadbd4def60ad08171cf60b0b2b6c7171ecfd99b580d60e4f037f9041b9205cf394d0c64d710c897953aa2235b0b",
)

DEEPNOTE_PROJECT_ID = os.environ.get("DEEPNOTE_PROJECT_ID", "24e7d245-fdf2-467e-ad2e-a8ff1f32272c")
DEEPNOTE_NOTEBOOK_ID = os.environ.get("DEEPNOTE_NOTEBOOK_ID", "4c7640a60b614139864ad550da0015e2")


def trigger_notebook(
    project_id: str = DEEPNOTE_PROJECT_ID,
    notebook_id: str = DEEPNOTE_NOTEBOOK_ID,
    api_key: str = DEEPNOTE_API_KEY,
) -> bool:
    """
    Trigger a Deepnote notebook to execute.

    Returns True if successfully triggered (202), False otherwise.
    """
    if not project_id or not notebook_id:
        logger.error(
            "DEEPNOTE_PROJECT_ID and DEEPNOTE_NOTEBOOK_ID must be set. "
            "Find them in your notebook URL: "
            "https://deepnote.com/workspace/{name}/project/{name}-{PROJECT_ID}"
            "/notebook/{name}-{NOTEBOOK_ID}"
        )
        return False

    url = (
        f"https://api.deepnote.com/v1/projects/{project_id}"
        f"/notebooks/{notebook_id}/execute"
    )

    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )

        if resp.status_code == 202:
            logger.info("Deepnote notebook triggered successfully (202 Accepted)")
            return True
        elif resp.status_code == 401:
            logger.error("Deepnote API: Unauthorized. Check API key and plan (Team required)")
            return False
        else:
            logger.warning(f"Deepnote API: unexpected status {resp.status_code}: {resp.text}")
            return False

    except Exception as e:
        logger.error(f"Deepnote trigger failed: {e}")
        return False


def check_api_key(api_key: str = DEEPNOTE_API_KEY) -> bool:
    """Quick check if API key format looks valid."""
    if not api_key:
        print("No API key set")
        return False

    if len(api_key) < 50:
        print("API key looks too short")
        return False

    print(f"API key: {api_key[:8]}...{api_key[-8:]}")
    print(f"Length: {len(api_key)} chars")
    print("Key format looks valid.")
    print()
    print("Next steps:")
    print("1. Create a Deepnote project at https://deepnote.com")
    print("2. Add a notebook with this code:")
    print("   !pip install requests numpy")
    print("   import sys; sys.path.insert(0, '.')")
    print("   from news_pipeline import NewsPipeline")
    print("   pipeline = NewsPipeline()")
    print("   pipeline.run()")
    print("   print(pipeline.get_latest_report())")
    print()
    print("3. Get project_id and notebook_id from the URL")
    print("4. Set environment variables:")
    print("   export DEEPNOTE_PROJECT_ID='xxx-xxx-xxx'")
    print("   export DEEPNOTE_NOTEBOOK_ID='xxxxx'")
    print("5. Run: python deepnote_trigger.py")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if "--check" in sys.argv:
        check_api_key()
    else:
        if not DEEPNOTE_PROJECT_ID:
            print("Project not configured yet. Run with --check for setup instructions.")
            check_api_key()
        else:
            success = trigger_notebook()
            sys.exit(0 if success else 1)
