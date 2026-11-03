"""Command line interface: parses commands, prompts the user, prints results."""

import argparse
import getpass
import sys

from ticketforge.client import ApiError, TicketForgeClient
from ticketforge.config import CONFIG_PATH, load_config, save_config


def ask(prompt, required=False):
    """Prompt until we get a value (or accept empty if not required)."""
    while True:
        value = input(prompt).strip()
        if value or not required:
            return value
        print("This field is required.")


def get_client():
    credentials = load_config()
    if credentials is None:
        sys.exit("Not configured yet. Run: python -m ticketforge setup")
    return TicketForgeClient(*credentials)


def cmd_setup(args):
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")

    # There is no login endpoint, so check the credentials with a real request.
    client = TicketForgeClient(username, password)
    try:
        client.list_tickets(limit=1)
    except ApiError as e:
        if e.status == 401:
            sys.exit("Invalid username or password.")
        raise

    save_config(username, password)
    print(f"Connected as {username}. Credentials saved to {CONFIG_PATH}")


def cmd_list(args):
    client = get_client()
    page = client.list_tickets()
    if not page["workitems"]:
        print("No tickets yet.")
        return

    print(f"{'REF':<8} {'STAGE':<12} TITLE")
    while True:
        for ticket in page["workitems"]:
            print(f"{ticket['ref']:<8} {ticket['stage']:<12} {ticket['title']}")

        # The API returns at most 5 tickets per page and a cursor for the next one.
        pagination = page["pagination"]
        if not pagination.get("hasMore"):
            break
        if not args.all and input("-- Press Enter for more, or q to quit: ").strip().lower() == "q":
            break
        page = client.list_tickets(cursor=pagination["nextCursor"])


def cmd_create(args):
    title, description = args.title, args.description
    if title is None:  # no flags given: ask interactively
        title = ask("Title: ", required=True)
        description = ask("Description (optional): ")
    elif not title.strip():
        sys.exit("Title cannot be empty.")

    depends_on = [ref.upper() for ref in args.depends_on] if args.depends_on else None
    client = get_client()
    ticket = client.create_ticket(title.strip(), description or None, depends_on)
    print(f"Created {ticket['ref']}: {ticket['title']}")


def main():
    parser = argparse.ArgumentParser(prog="ticketforge", description="Manage TicketForge tickets from the terminal.")
    commands = parser.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="connect to TicketForge and save your credentials")
    setup.set_defaults(func=cmd_setup)

    list_ = commands.add_parser("list", help="list your tickets, newest first")
    list_.add_argument("--all", action="store_true", help="show every page without asking")
    list_.set_defaults(func=cmd_list)

    create = commands.add_parser("create", help="create a ticket (prompts if --title is missing)")
    create.add_argument("--title")
    create.add_argument("--description")
    create.add_argument("--depends-on", nargs="+", metavar="REF", help="refs this ticket depends on, e.g. TF-1 TF-2")
    create.set_defaults(func=cmd_create)

    args = parser.parse_args()
    try:
        args.func(args)
    except ApiError as e:
        sys.exit(f"Error: {e}")
