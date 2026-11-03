"""Command line interface: parses commands, prompts the user, prints results."""

import argparse
import getpass
import sys

from ticketforge.client import ApiError, TicketForgeClient
from ticketforge.config import CONFIG_PATH, load_config, save_config

STAGES = ["open", "in_progress", "review", "closed"]


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
        sys.exit("Not logged in. Run: python -m ticketforge login (or register)")
    return TicketForgeClient(*credentials)


def ask_credentials():
    username = ask("Username: ", required=True)
    password = getpass.getpass("Password: ")
    return username, password


def cmd_login(args):
    username, password = ask_credentials()

    # There is no login endpoint, so check the credentials with a real request.
    client = TicketForgeClient(username, password)
    try:
        client.list_tickets(limit=1)
    except ApiError as e:
        if e.status == 401:
            sys.exit("Invalid username or password.")
        raise

    save_config(username, password)
    print(f"Logged in as {username}. Credentials saved to {CONFIG_PATH}")


def cmd_register(args):
    username, password = ask_credentials()
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("Passwords do not match.")

    # The server checks the rules (username 3+ chars, password 6+, not taken).
    TicketForgeClient(username, password).register(username, password)
    save_config(username, password)
    print(f"Registered and logged in as {username}. Credentials saved to {CONFIG_PATH}")


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


def cmd_show(args):
    ticket = get_client().get_ticket(args.ref.upper())
    print(f"{ticket['ref']}  {ticket['title']}")
    print(f"  Stage:       {ticket['stage']}")
    print(f"  Description: {ticket['description'] or '-'}")
    print(f"  Depends on:  {', '.join(ticket.get('dependsOn') or []) or '-'}")
    for name, value in (ticket.get("customFields") or {}).items():
        print(f"  {name + ':':<12} {value}")
    print(f"  Created:     {ticket['created']}")
    print(f"  Updated:     {ticket['updated']}")


def cmd_create(args):
    title, description = args.title, args.description
    if title is None:  # no flags given: ask interactively
        title = ask("Title: ", required=True)
        if description is None:
            description = ask("Description (optional): ")
    elif not title.strip():
        sys.exit("Title cannot be empty.")

    depends_on = [ref.upper() for ref in args.depends_on] if args.depends_on else None
    client = get_client()
    ticket = client.create_ticket(title.strip(), description or None, depends_on)
    print(f"Created {ticket['ref']}: {ticket['title']}")


def ask_stage(current):
    while True:
        stage = ask(f"Stage ({'/'.join(STAGES)}) [{current}]: ") or current
        if stage in STAGES:
            return stage
        print(f"Stage must be one of: {', '.join(STAGES)}")


def cmd_update(args):
    client = get_client()
    ticket = client.get_ticket(args.ref.upper())

    if args.title is None and args.description is None and args.stage is None and args.depends_on is None:
        # no flags given: ask for each field, Enter keeps the current value
        print(f"Editing {ticket['ref']}. Press Enter to keep the current value.")
        wanted = {
            "title": ask(f"Title [{ticket['title']}]: ") or ticket["title"],
            "description": ask(f"Description [{ticket['description'] or ''}]: ") or ticket["description"],
            "stage": ask_stage(ticket["stage"]),
        }
    else:
        if args.title is not None and not args.title.strip():
            sys.exit("Title cannot be empty.")
        wanted = {
            "title": args.title and args.title.strip(),
            "description": args.description,
            "stage": args.stage,
            "dependsOn": args.depends_on and [ref.upper() for ref in args.depends_on],
        }

    changes = {key: value for key, value in wanted.items() if value is not None and value != ticket.get(key)}
    if not changes:
        print("Nothing to change.")
        return

    client.update_ticket(ticket, **changes)
    print(f"Updated {ticket['ref']}:")
    for key, value in changes.items():
        print(f"  {key}: {ticket.get(key)} -> {value}")


def cmd_fields_list(args):
    fields = get_client().list_fields()
    if not fields:
        print("No custom fields yet.")
    for field in fields:
        print(f"{field['name']:<16} {field['label']}")


def cmd_fields_add(args):
    field = get_client().add_field(args.name, args.label)
    print(f"Added field {field['name']} ({field['label']}).")


def cmd_fields_delete(args):
    # The API deletes by id, but users know fields by name.
    client = get_client()
    field = next((f for f in client.list_fields() if f["name"] == args.name), None)
    if field is None:
        sys.exit(f"No custom field named {args.name}.")
    client.delete_field(field["id"])
    print(f"Deleted field {args.name}.")


def main():
    parser = argparse.ArgumentParser(prog="ticketforge", description="Manage TicketForge tickets from the terminal.")
    commands = parser.add_subparsers(dest="command", required=True)

    login = commands.add_parser("login", aliases=["setup"], help="log in to TicketForge and save your credentials")
    login.set_defaults(func=cmd_login)

    register = commands.add_parser("register", help="create a TicketForge account and log in")
    register.set_defaults(func=cmd_register)

    list_ = commands.add_parser("list", help="list your tickets, newest first")
    list_.add_argument("--all", action="store_true", help="show every page without asking")
    list_.set_defaults(func=cmd_list)

    show = commands.add_parser("show", help="show one ticket in full")
    show.add_argument("ref", help="ticket ref, e.g. TF-3")
    show.set_defaults(func=cmd_show)

    create = commands.add_parser("create", help="create a ticket (prompts if --title is missing)")
    create.add_argument("--title")
    create.add_argument("--description")
    create.add_argument("--depends-on", nargs="+", metavar="REF", help="refs this ticket depends on, e.g. TF-1 TF-2")
    create.set_defaults(func=cmd_create)

    update = commands.add_parser("update", help="update a ticket (prompts if no flags are given)")
    update.add_argument("ref", help="ticket ref, e.g. TF-3")
    update.add_argument("--title")
    update.add_argument("--description")
    update.add_argument("--stage", choices=STAGES)
    update.add_argument("--depends-on", nargs="+", metavar="REF")
    update.set_defaults(func=cmd_update)

    fields = commands.add_parser("fields", help="manage custom fields")
    field_commands = fields.add_subparsers(dest="action", required=True)
    field_commands.add_parser("list", help="list custom fields").set_defaults(func=cmd_fields_list)
    add = field_commands.add_parser("add", help="add a custom field")
    add.add_argument("name", help="letters, numbers and underscores, e.g. priority")
    add.add_argument("label", help="display label, e.g. Priority")
    add.set_defaults(func=cmd_fields_add)
    delete = field_commands.add_parser("delete", help="delete a custom field")
    delete.add_argument("name")
    delete.set_defaults(func=cmd_fields_delete)

    args = parser.parse_args()
    try:
        args.func(args)
    except ApiError as e:
        sys.exit(f"Error: {e}")
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nCancelled.")
