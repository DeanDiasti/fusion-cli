"""
CadBot agent loop — drives the OpenAI Codex SDK against the local Fusion bridge.

Auth uses your ChatGPT (Codex) subscription: `codex login` once, done.
The installed SDK (0.154.x) doesn't expose custom function tools; instead the
agent gets the bridge CLI (agent/bridge_cli.py) and calls CAD tools as shell
commands, which the app-server executes in the workspace sandbox.

Run:  .venv/bin/python agent/codex_agent.py        (interactive)
      .venv/bin/python agent/codex_agent.py --prompt "..."
"""

import argparse
import json
import os
import sys
from bridge_cli import BRIDGE_URL, runtime_status

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CLI = os.path.join(HERE, "bridge_cli.py")
PYTHON = sys.executable

def build_system_prompt():
    return """You are CadBot inside Fusion. Use the structured CLI:
{python} {cli} help
{python} {cli} bodies list
Discover commands and flags with help. Lengths are mm and angles degrees.
No Python execution or arbitrary API access is offered. Use only documented commands.
Inspect the design before editing and verify results after editing. Edit commands
require an active Fusion chat message checkpoint; use the in-Fusion chat for modeling.
""".format(python=PYTHON, cli=os.path.join(HERE, 'fusion_cli.py'))



def check_bridge():
    result, status = runtime_status()
    if status >= 400:
        print('ERROR: ' + result['error'])
        return False
    print('Bridge OK:', result['runtime'])
    return True


def main():
    parser = argparse.ArgumentParser(description="CadBot agent (Codex-powered)")
    parser.add_argument("--prompt", help="One-shot prompt; omit for interactive chat")
    parser.add_argument("--new", action="store_true", help="Deprecated; reset requires a checkpoint in the Fusion chat")
    args = parser.parse_args()

    if args.new:
        parser.error("--new cannot reset a design outside a message checkpoint. Use the Fusion chat to reset safely.")

    if not check_bridge():
        sys.exit(1)

    from openai_codex import ApprovalMode, Codex, Sandbox

    with Codex() as codex:
        thread = codex.thread_start(
            cwd=REPO,
            sandbox=Sandbox.read_only,
            approval_mode=ApprovalMode.deny_all,  # fully autonomous, no prompts
            developer_instructions=build_system_prompt(),
        )

        if args.prompt:
            result = thread.run(args.prompt)
            print(result.final_response)
            return

        print("CadBot interactive. Type a request, or 'quit' to exit.")
        while True:
            try:
                text = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text or text.lower() in ("quit", "exit"):
                break
            result = thread.run(text)
            print("\nCadBot: {}".format(result.final_response))


if __name__ == "__main__":
    main()
