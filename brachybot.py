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
    parser.add_argument(
        "--tumor-type",
        help="CTV model/site (required for automatic CTV segmentation without --ctv)",
    )
    parser.add_argument("--mode", choices=["rule_based", "rl", "auto"], default="rule_based", help="Planning mode")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--chat", action="store_true", help="Start interactive chat mode")
    parser.add_argument("--server", action="store_true", help="Start web server")
    parser.add_argument(
        "--port", type=int, default=os.environ.get("BRACHY_PORT", "8080"),
        help="Web server port (default: BRACHY_PORT or 8080)",
    )
    parser.add_argument(
        "--host", default=os.environ.get("BRACHY_HOST", "127.0.0.1"),
        help="Web server host (default: BRACHY_HOST or 127.0.0.1)",
    )
    parser.add_argument("--session", default="default", help="Session ID")

    args = parser.parse_args()

    if args.chat:
        return _run_chat(args.session)
    elif args.server:
        return _run_server(args.port, args.host)
    elif args.ct_path:
        return _run_planning(args)
    else:
        parser.print_help()
        return 0


def _run_planning(args):
    agent = BrachyAgent(session_id=args.session)

    result = agent.run_preoperative_plan(
        ct_path=args.ct_path,
        ctv_path=args.ctv_path,
        oar_path=args.oar_path,
        mode=args.mode,
        output_dir=args.output,
        tumor_type=args.tumor_type,
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


def _run_server(port, host="127.0.0.1"):
    try:
        import web.server
    except ImportError as exc:
        print(f"Cannot start the web server: {exc}", file=sys.stderr)
        print("Install server dependencies with: pip install -r requirements.txt", file=sys.stderr)
        return 2

    provider_env = (
        ("Anthropic", ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"), "ANTHROPIC_MODEL"),
        ("OpenAI", ("OPENAI_API_KEY",), "OPENAI_MODEL"),
        ("OpenRouter", ("OPENROUTER_API_KEY",), "OPENROUTER_MODEL"),
        ("Qwen", ("DASHSCOPE_API_KEY",), "QWEN_MODEL"),
        ("Kimi", ("MOONSHOT_API_KEY",), "KIMI_MODEL"),
        ("MiniMax", ("MINIMAX_API_KEY",), "MINIMAX_MODEL"),
        ("GLM", ("ZHIPU_API_KEY",), "GLM_MODEL"),
        ("Gemini", ("GOOGLE_API_KEY",), "GEMINI_MODEL"),
        ("Groq", ("GROQ_API_KEY",), "GROQ_MODEL"),
        ("Grok", ("XAI_API_KEY",), "GROK_MODEL"),
        ("MiMo", ("MIMO_API_KEY",), "MIMO_MODEL"),
        ("DeepSeek", ("DEEPSEEK_API_KEY",), "DEEPSEEK_MODEL"),
        ("Tencent", ("TENCENT_API_KEY",), "TENCENT_MODEL"),
    )
    configured = []
    for provider, key_names, model_name in provider_env:
        if any(os.environ.get(name) for name in key_names):
            configured.append(
                f"{provider}" + (f" ({os.environ[model_name]})" if os.environ.get(model_name) else "")
            )
    print("Configured LLM providers: " + (", ".join(configured) if configured else "none"))

    print(f"\nStarting BrachyBot web server on {host}:{port}...")
    browser_host = "localhost" if host in {"0.0.0.0", "::", "127.0.0.1", "::1"} else host
    print(f"Open http://{browser_host}:{port} in your browser")
    try:
        web.server.run_server(port=port, host=host)
    except RuntimeError as exc:
        print(f"Web server startup refused: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Web server failed to bind to port {port}: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(
                f"Web server stopped during startup. Port {port} may already be in use.",
                file=sys.stderr,
            )
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
