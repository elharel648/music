"""Entry point for the packaged app and for `python run_flow.py`. With arguments it runs the CLI."""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("analyze", "build", "plugins", "license", "activate", "--version", "-h", "--help"):
        from flow.cli import main
        sys.exit(main())
    from flow.app import main
    main()
