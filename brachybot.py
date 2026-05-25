"""
BrachyBot - AI-BrachyAgent System Entry Point
============================================
LLM-driven closed-loop brachytherapy planning system.
Run: python BrachyBot/brachybot.py --help
"""

import os
import sys

_BRACHYBOT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BRACHYBOT_ROOT)

from AgenticSys import BrachyAgent


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="BrachyBot - AI-BrachyAgent Brachytherapy Planning System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Pre-operative planning
  python brachybot.py --ct path/to/ct.nii.gz --ctv path/to/ctv.nii.gz --mode rule_based

  # Interactive chat mode
  python brachybot.py --chat

  # Start web interface
  python brachybot.py --server --port 8080
        """,
    )

    parser.add_argument("--ct", dest="ct_path", help="Path to CT image (.nii.gz)")
    parser.add_argument("--ctv", dest="ctv_path", help="Path to CTV mask (.nii.gz)")
    parser.add_argument("--oar", dest="oar_path", help="Path to OAR mask (.nii.gz)")
    parser.add_argument("--mode", choices=["rule_based", "rl"], default="rule_based", help="Planning mode")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--chat", action="store_true", help="Start interactive chat mode")
    parser.add_argument("--server", action="store_true", help="Start web server")
    parser.add_argument("--port", type=int, default=8080, help="Web server port")
    parser.add_argument("--session", default="default", help="Session ID")

    args = parser.parse_args()

    if args.chat:
        _run_chat(args.session)
    elif args.server:
        _run_server(args.port)
    elif args.ct_path:
        _run_planning(args)
    else:
        parser.print_help()


def _run_planning(args):
    agent = BrachyAgent(session_id=args.session)

    result = agent.run_preoperative_plan(
        ct_path=args.ct_path,
        ctv_path=args.ctv_path,
        oar_path=args.oar_path,
        mode=args.mode,
        output_dir=args.output,
    )

    if result["success"]:
        print(f"\n✅ Planning completed successfully!")
        print(f"   Seeds placed: {result.get('total_seeds', 0)}")
        print(f"   Trajectories: {result.get('num_trajectories', 0)}")
        metrics = result.get("metrics", {})
        print(f"   V100: {metrics.get('v100', 0):.1%}")
        print(f"   D90: {metrics.get('d90', 0):.2f} Gy")
        print(f"   Plan Score: {metrics.get('plan_score', 0):.0f}/100")
    else:
        print(f"\n❌ Planning failed: {result.get('error', 'Unknown error')}")


def _run_chat(session_id):
    agent = BrachyAgent(session_id=session_id)
    print("\n" + "=" * 50)
    print("  BrachyBot Chat Mode")
    print("  Type 'exit' or 'quit' to end")
    print("=" * 50 + "\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if user_input.lower() in ["exit", "quit", "q"]:
                print("Goodbye!")
                break
            if not user_input:
                continue

            response = agent.chat(user_input)
            print(f"BrachyBot: {response}\n")

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break


def _run_server(port):
    import web.server

    # Auto-detect MiniMax proxy config from environment
    minimax_base = os.environ.get("ANTHROPIC_BASE_URL", "")
    minimax_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if minimax_base and minimax_token:
        os.environ["ANTHROPIC_BASE_URL"] = minimax_base
        os.environ["ANTHROPIC_AUTH_TOKEN"] = minimax_token
        os.environ["ANTHROPIC_MODEL"] = os.environ.get("ANTHROPIC_MODEL", "MiniMax-M2.7-highspeed")
        os.environ["BRACHY_LLM_PROVIDER"] = "anthropic"
        print(f"Using MiniMax proxy: {minimax_base}")
        print(f"Model: {os.environ['ANTHROPIC_MODEL']}")

    print(f"\nStarting BrachyBot web server on port {port}...")
    print(f"Open http://localhost:{port} in your browser")
    web.server.run_server(port=port)


if __name__ == "__main__":
    main()