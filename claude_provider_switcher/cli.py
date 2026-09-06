from __future__ import annotations

import argparse
import getpass
import json
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from .core import Switcher
from .credentials import validate_secret
from .probe import probe
from .profiles import Profile, validate_name
from .storage import SwitcherError, mutation_lock


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid command arguments. Use --help; values omitted to protect credentials.\n")


def parser() -> argparse.ArgumentParser:
    cli = PrivateArgumentParser(description="Manage Claude Code provider profiles without modifying conversations.")
    cli.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    cli.add_argument("--home", type=Path, help="Switcher data directory")
    cli.add_argument("--claude-home", type=Path, help="Claude configuration directory (defaults to CLAUDE_CONFIG_DIR or ~/.claude)")
    commands = cli.add_subparsers(dest="command")
    commands.add_parser("menu", help="Interactive menu")
    status = commands.add_parser("status", help="Show local configuration, not remote login status")
    status.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor", help="Diagnose local provider overrides without executing helpers")
    doctor.add_argument("--project", type=Path, default=Path.cwd())
    doctor.add_argument("--json", action="store_true")
    use = commands.add_parser("use", help="Back up and update Claude user settings")
    use.add_argument("name")
    use.add_argument("--no-repair-history", action="store_true", help="Skip the project record reconciliation that normally follows a switch")
    repair = commands.add_parser("repair-history", help="Reconcile duplicated project records without switching profile")
    repair.add_argument("--check", action="store_true", help="Report only; write nothing")
    repair.add_argument("--json", action="store_true")
    run = commands.add_parser("run", help="Start Claude with isolated provider settings for one process")
    run.add_argument("name")
    run.add_argument("args", nargs=argparse.REMAINDER, help="Claude flags after --")
    profile = commands.add_parser("profile", help="Manage provider profiles")
    profiles = profile.add_subparsers(dest="action", required=True)
    profiles.add_parser("list")
    for action in ("add", "edit"):
        add = profiles.add_parser(action)
        add.add_argument("name")
        if action == "add":
            add.add_argument("--type", choices=["api", "subscription"], default="api")
        add.add_argument("--base-url")
        add.add_argument("--model")
        add.add_argument("--auth-kind", choices=["api_key", "auth_token"])
        if action == "add":
            add.add_argument("--key-stdin", action="store_true", help="Read the key from stdin without echo")
    key = profiles.add_parser("key")
    key.add_argument("name")
    key.add_argument("--key-stdin", action="store_true")
    remove = profiles.add_parser("remove")
    remove.add_argument("name")
    remove.add_argument("--yes", action="store_true")
    test = profiles.add_parser("test")
    test.add_argument("name")
    test.add_argument("--inference", action="store_true", help="Explicit opt-in to a one-token request; may incur charges")
    test.add_argument("--timeout", type=float, default=15)
    backups = commands.add_parser("backup", help="List or restore settings backups")
    backup = backups.add_subparsers(dest="action", required=True)
    backup.add_parser("list")
    restore = backup.add_parser("restore")
    restore.add_argument("id")
    restore.add_argument("--yes", action="store_true")
    return cli


def read_secret(from_stdin: bool) -> str:
    if from_stdin:
        secret = sys.stdin.readline(4097).rstrip("\r\n")
    elif sys.stdin.isatty():
        secret = getpass.getpass("API credential (hidden): ")
    else:
        raise SwitcherError("No interactive terminal. Use --key-stdin and pipe the credential from your secret manager.")
    validate_secret(secret)
    return secret


def confirm(message: str, yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty() or input(message + " [y/N]: ").strip().lower() != "y":
        raise SwitcherError("Operation cancelled. Use --yes for a deliberate noninteractive operation.")


def history_message(report: dict) -> None:
    if report["duplicate_folders"]:
        verb, tense = ("merged", "updated") if report["applied"] else ("would merge", "to update")
        print(
            f"History: {verb} {report['duplicate_folders']} folder(s) recorded under several path forms; "
            f"{report['project_entries_updated']} project entr(ies) and "
            f"{report['history_entries_normalized']} prompt record(s) {tense}."
        )
    else:
        print("History: project records are consistent; nothing to reconcile.")
    if report["backup"]:
        print(f"History backup: {report['backup']}")
    print("Conversations are kept per working directory and are not filtered by provider, so switching never hides them.")


def switch_message(switcher: Switcher, name: str, repair_history: bool = True):
    profile = switcher.profiles.get(name)
    if profile.type == "api" and not switcher.credentials.get(name) and sys.stdin.isatty():
        secret = read_secret(False)
        with mutation_lock(switcher.root):
            backend = switcher.credentials.set(name, secret)
        print(f"Credential saved using {backend} storage.")
    backup = switcher.use(name)
    print(f"Configured profile: {name}")
    print(f"Backup: {backup}")
    print("Restart Claude Code. This updated user settings only; shell, project or managed overrides may still apply.")
    print("Check 'ccs doctor' and Claude's /status. Subscription login is not performed by this tool.")
    if repair_history:
        history_message(switcher.repair_history())


def execute(args, switcher: Switcher) -> int:
    if args.command == "use":
        switch_message(switcher, args.name, not args.no_repair_history)
    elif args.command == "repair-history":
        report = switcher.repair_history(apply=not args.check)
        if args.json:
            print(json.dumps(report, ensure_ascii=True, indent=2))
        else:
            for key, value in report.items():
                print(f"{key}: {', '.join(value) if isinstance(value, list) else value}")
            history_message(report)
        return 1 if args.check and report["duplicate_folders"] else 0
    elif args.command in {None, "status"}:
        status = switcher.status()
        if getattr(args, "json", False):
            print(json.dumps(status, ensure_ascii=True, indent=2))
        else:
            for key, value in status.items():
                print(f"{key}: {value}")
    elif args.command == "doctor":
        findings = switcher.doctor(args.project)
        if args.json:
            print(json.dumps({"findings": findings, "limitations": "Does not evaluate MDM, registry, remote policy or CLI overrides. Verify with Claude /status."}, indent=2, ensure_ascii=True))
        else:
            for finding in findings:
                print(f"{finding['source']}: {', '.join(finding['keys'])}\n  {finding['issue']}")
            if not findings:
                print("No local conflicts detected.")
            print("Not a complete policy evaluator: MDM, registry, remote policy and CLI flags are not inspected. Verify /status in Claude Code.")
        return 1 if findings else 0
    elif args.command == "run":
        arguments = args.args[1:] if args.args[:1] == ["--"] else args.args
        return switcher.run(args.name, arguments)
    elif args.command == "backup":
        if args.action == "list":
            print("\n".join(switcher.backups()) or "No settings backups.")
        else:
            confirm("Restore this backup over current user settings? Current settings will also be backed up.", args.yes)
            print(f"Restored. Undo backup: {switcher.restore(args.id)}")
    elif args.command == "profile":
        profiles = switcher.profiles.load()
        if args.action == "list":
            for name, profile in profiles.items():
                print(f"{name}\t{profile.type}\t{profile.model}\t{profile.base_url}")
        elif args.action == "add":
            validate_name(args.name)
            if args.name in profiles:
                raise SwitcherError("Profile already exists. Use 'profile edit'.")
            url, model = args.base_url, args.model
            if args.type == "api":
                if sys.stdin.isatty():
                    url = url or input("Anthropic-compatible base URL: ").strip()
                    model = model or input("Model ID: ").strip()
                profile = Profile("api", url or "", model or "", args.auth_kind or "api_key")
                profile.validate()
                secret = read_secret(args.key_stdin)
            else:
                if url or model or args.auth_kind or args.key_stdin:
                    raise SwitcherError("Subscription profiles do not accept API options.")
                profile, secret = Profile("subscription"), None
            with mutation_lock(switcher.root):
                profiles = switcher.profiles.load()
                if args.name in profiles:
                    raise SwitcherError("Profile was added by another operation.")
                if secret:
                    backend = switcher.credentials.set(args.name, secret)
                    print(f"Credential storage: {backend}")
                profiles[args.name] = profile
                switcher.profiles.save(profiles)
            print(f"Added profile: {args.name}")
        elif args.action == "edit":
            old = switcher.profiles.get(args.name)
            if old.type != "api":
                raise SwitcherError("Subscription profiles have no API fields to edit.")
            fields = {k: getattr(args, k) for k in ("base_url", "model", "auth_kind") if getattr(args, k) is not None}
            if not fields:
                raise SwitcherError("Specify --base-url, --model or --auth-kind.")
            with mutation_lock(switcher.root):
                profiles = switcher.profiles.load()
                updated = replace(profiles[args.name], **fields)
                updated.validate()
                profiles[args.name] = updated
                switcher.profiles.save(profiles)
            print("Profile updated. Existing settings were not changed; run 'ccs use' again.")
        elif args.action == "key":
            if switcher.profiles.get(args.name).type != "api":
                raise SwitcherError("Subscription profiles do not use API keys.")
            secret = read_secret(args.key_stdin)
            with mutation_lock(switcher.root):
                backend = switcher.credentials.set(args.name, secret)
            print(f"Credential saved using {backend} storage.")
        elif args.action == "remove":
            switcher.profiles.get(args.name)
            current = switcher._read_settings()
            if switcher.configured_name(current) == args.name or current.get("apiKeyHelper") == switcher.helper_command(args.name):
                raise SwitcherError("Profile is referenced by current user settings. Switch or restore settings first.")
            confirm("Remove this profile and its switcher credential?", args.yes)
            with mutation_lock(switcher.root), mutation_lock(switcher.claude_home):
                profiles = switcher.profiles.load()
                current = switcher._read_settings()
                if switcher.configured_name(current) == args.name or current.get("apiKeyHelper") == switcher.helper_command(args.name):
                    raise SwitcherError("Profile became active during confirmation. Switch or restore settings first.")
                profiles.pop(args.name)
                switcher.profiles.save(profiles)
                switcher.credentials.delete(args.name)
            print("Profile removed. Historical settings backups are retained and may reference it.")
        elif args.action == "test":
            if not 0 < args.timeout <= 120:
                raise SwitcherError("Timeout must be greater than 0 and at most 120 seconds.")
            profile = switcher.profiles.get(args.name)
            if profile.type != "api":
                raise SwitcherError("Subscription profiles cannot be API-tested.")
            secret = switcher.credentials.get(args.name)
            if not secret:
                raise SwitcherError("Credential unavailable. Set it with 'profile key'.")
            result = probe(profile, secret, inference=args.inference, timeout=args.timeout)
            print(json.dumps(result, ensure_ascii=True))
    return 0


def menu(cli, switcher: Switcher):
    def choose(api_only=False):
        profiles = switcher.profiles.load()
        names = [k for k, v in profiles.items() if not api_only or v.type == "api"]
        if not names:
            raise SwitcherError("No matching profiles.")
        for index, name in enumerate(names, 1):
            print(f"{index}. {name}")
        try:
            index = int(input("Choose profile: "))
            if not 1 <= index <= len(names):
                raise ValueError()
        except ValueError:
            raise SwitcherError("Invalid selection.") from None
        return names[index - 1]

    while True:
        print("\n1. Switch provider\n2. Show status\n3. Test provider connectivity\n4. Manage profiles\n5. Diagnose configuration\n6. Restore settings\n7. Reconcile history records\n0. Exit")
        try:
            choice = input("Choose: ").strip()
            if choice == "0":
                return 0
            if choice == "1":
                execute(cli.parse_args(["use", choose()]), switcher)
            elif choice == "2":
                execute(cli.parse_args(["status"]), switcher)
            elif choice == "3":
                execute(cli.parse_args(["profile", "test", choose(True)]), switcher)
            elif choice == "4":
                print("1. List\n2. Add API profile\n3. Set credential\n4. Remove\n5. Edit API profile")
                action = input("Choose: ").strip()
                if action == "1":
                    command = ["profile", "list"]
                elif action == "2":
                    command = ["profile", "add", input("Profile name: ").strip()]
                elif action in {"3", "4"}:
                    command = ["profile", "key" if action == "3" else "remove", choose(action == "3")]
                elif action == "5":
                    name = choose(True)
                    command = ["profile", "edit", name]
                    for field, prompt in (("base-url", "Base URL"), ("model", "Model"), ("auth-kind", "Auth kind (api_key/auth_token)")):
                        value = input(prompt + " (blank to keep): ").strip()
                        if value:
                            command.extend(["--" + field, value])
                else:
                    raise SwitcherError("Invalid selection.")
                execute(cli.parse_args(command), switcher)
            elif choice == "5":
                execute(cli.parse_args(["doctor"]), switcher)
            elif choice == "6":
                execute(cli.parse_args(["backup", "list"]), switcher)
                execute(cli.parse_args(["backup", "restore", input("Backup ID: ").strip()]), switcher)
            elif choice == "7":
                execute(cli.parse_args(["repair-history"]), switcher)
            else:
                print("Invalid selection.")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        except SwitcherError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
        except SystemExit:
            print("Invalid menu arguments.", file=sys.stderr)


def main(argv=None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    try:
        switcher = Switcher(args.home, args.claude_home)
        if args.command == "menu" or (args.command is None and sys.stdin.isatty()):
            return menu(cli, switcher)
        return execute(args, switcher)
    except SwitcherError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Cancelled.", file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError):
        print("ERROR: Operation failed; check file permissions and configuration. Details omitted to protect credentials.", file=sys.stderr)
        return 1
