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


def ask_ref(client, args):
    """Use the ref from the command line, or let the user pick from their tickets."""
    if args.ref:
        return args.ref.upper()

    refs, page = [], client.list_tickets()
    while True:
        for ticket in page["workitems"]:
            refs.append(ticket["ref"])
            print(f"{len(refs):>3}. {ticket['ref']:<8} {ticket['stage']:<12} {ticket['title']}")
        if not refs:
            sys.exit("No tickets yet. Create one with: python -m ticketforge create")

        has_more = page["pagination"].get("hasMore")
        prompt = f"Choose a ticket (1-{len(refs)}" + (", or Enter for more" if has_more else "") + "): "
        while True:
            answer = input(prompt).strip()
            if answer.isdigit() and 1 <= int(answer) <= len(refs):
                return refs[int(answer) - 1]
            if not answer and has_more:
                break
            print(f"Please enter a number from 1 to {len(refs)}.")
        page = client.list_tickets(cursor=page["pagination"]["nextCursor"])


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
    client = get_client()
    ticket = client.get_ticket(ask_ref(client, args))
    print(f"{ticket['ref']}  {ticket['title']}")
    print(f"  Stage:       {ticket['stage']}")
    print(f"  Description: {ticket['description'] or '-'}")
    print(f"  Depends on:  {', '.join(ticket.get('dependsOn') or []) or '-'}")
    for name, value in (ticket.get("customFields") or {}).items():
        print(f"  {name + ':':<12} {value}")
    print(f"  Created:     {ticket['created']}")
    print(f"  Updated:     {ticket['updated']}")


def parse_fields(pairs):
    """Turn ["priority=high", ...] into {"priority": "high"}."""
    fields = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep or not name:
            sys.exit(f"Invalid --field '{pair}', expected name=value.")
        fields[name] = value
    return fields


def ask_fields(client, current):
    """Ask for every custom field. Enter keeps the current value, '-' clears it."""
    values = dict(current)
    for field in client.list_fields():
        name = field["name"]
        answer = ask(f"{field['label']} [{current.get(name, '')}]: ")
        if answer == "-":
            values.pop(name, None)
        elif answer:
            values[name] = answer
    return values


def cmd_create(args):
    client = get_client()
    title, description = args.title, args.description
    custom_fields = parse_fields(args.field or [])
    if title is None:  # no title flag: ask interactively
        title = ask("Title: ", required=True)
        if description is None:
            description = ask("Description (optional): ")
        if not custom_fields:
            custom_fields = ask_fields(client, {})
    elif not title.strip():
        sys.exit("Title cannot be empty.")

    depends_on = [ref.upper() for ref in args.depends_on] if args.depends_on else None
    ticket = client.create_ticket(title.strip(), description or None, depends_on, custom_fields)
    print(f"Created {ticket['ref']}: {ticket['title']}")


def ask_stage(current):
    while True:
        stage = ask(f"Stage ({'/'.join(STAGES)}) [{current}]: ") or current
        if stage in STAGES:
            return stage
        print(f"Stage must be one of: {', '.join(STAGES)}")


def cmd_update(args):
    client = get_client()
    ticket = client.get_ticket(ask_ref(client, args))
    ticket["customFields"] = ticket.get("customFields") or {}  # missing when the ticket has none

    flags = (args.title, args.description, args.stage, args.depends_on, args.field, args.remove_field)
    if all(flag is None for flag in flags):
        # no flags given: ask for each field, Enter keeps the current value
        print(f"Editing {ticket['ref']}. Press Enter to keep the current value ('-' clears a custom field).")
        wanted = {
            "title": ask(f"Title [{ticket['title']}]: ") or ticket["title"],
            "description": ask(f"Description [{ticket['description'] or ''}]: ") or ticket["description"],
            "stage": ask_stage(ticket["stage"]),
            "customFields": ask_fields(client, ticket["customFields"]),
        }
    else:
        if args.title is not None and not args.title.strip():
            sys.exit("Title cannot be empty.")
        custom_fields = None
        if args.field or args.remove_field:
            custom_fields = {**ticket["customFields"], **parse_fields(args.field or [])}
            for name in args.remove_field or []:
                custom_fields.pop(name, None)
        wanted = {
            "title": args.title and args.title.strip(),
            "description": args.description,
            "stage": args.stage,
            "dependsOn": args.depends_on and [ref.upper() for ref in args.depends_on],
            "customFields": custom_fields,
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
    if args.action is None:  # plain `fields`: also show what can be done
        print()
        print("To manage fields run: fields add, fields rename or fields delete (each asks for what it needs).")


def cmd_fields_add(args):
    name = args.name or ask("Field name (letters, numbers, _; e.g. priority): ", required=True)
    label = args.label or ask(f"Display label [{name}]: ") or name
    field = get_client().add_field(name, label)
    print(f"Added field {field['name']} ({field['label']}).")


def find_field(client, name):
    """Find a field by name, or let the user pick one from a numbered list."""
    fields = client.list_fields()
    if not fields:
        sys.exit("No custom fields yet. Add one with: python -m ticketforge fields add")
    if name:
        # The API changes fields by id, but users know them by name.
        field = next((f for f in fields if f["name"] == name), None)
        if field is None:
            sys.exit(f"No custom field named {name}.")
        return field

    for number, field in enumerate(fields, 1):
        print(f"{number:>3}. {field['name']:<16} {field['label']}")
    while True:
        answer = input(f"Choose a field (1-{len(fields)}): ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(fields):
            return fields[int(answer) - 1]
        print(f"Please enter a number from 1 to {len(fields)}.")


def cmd_fields_rename(args):
    client = get_client()
    field = find_field(client, args.name)
    label = args.label or ask(f"New label for {field['name']} [{field['label']}]: ", required=True)
    client.rename_field(field["id"], label)
    print(f"Renamed field {field['name']} to {label}.")


def cmd_fields_delete(args):
    client = get_client()
    field = find_field(client, args.name)
    if args.name is None and ask(f"Delete field {field['name']}? [y/N]: ").lower() != "y":
        print("Nothing deleted.")
        return
    client.delete_field(field["id"])
    print(f"Deleted field {field['name']}.")


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
    show.add_argument("ref", nargs="?", help="ticket ref, e.g. TF-3 (asked if missing)")
    show.set_defaults(func=cmd_show)

    create = commands.add_parser("create", help="create a ticket (prompts if --title is missing)")
    create.add_argument("--title")
    create.add_argument("--description")
    create.add_argument("--depends-on", nargs="+", metavar="REF", help="refs this ticket depends on, e.g. TF-1 TF-2")
    create.add_argument("--field", action="append", metavar="NAME=VALUE", help="set a custom field (repeatable)")
    create.set_defaults(func=cmd_create)

    update = commands.add_parser("update", help="update a ticket (prompts if no flags are given)")
    update.add_argument("ref", nargs="?", help="ticket ref, e.g. TF-3 (asked if missing)")
    update.add_argument("--title")
    update.add_argument("--description")
    update.add_argument("--stage", choices=STAGES)
    update.add_argument("--depends-on", nargs="+", metavar="REF")
    update.add_argument("--field", action="append", metavar="NAME=VALUE", help="set a custom field (repeatable)")
    update.add_argument("--remove-field", action="append", metavar="NAME", help="clear a custom field (repeatable)")
    update.set_defaults(func=cmd_update)

    fields = commands.add_parser("fields", help="manage custom fields")
    fields.set_defaults(func=cmd_fields_list)  # `fields` alone lists them
    field_commands = fields.add_subparsers(dest="action")
    field_commands.add_parser("list", help="list custom fields").set_defaults(func=cmd_fields_list)
    add = field_commands.add_parser("add", help="add a custom field (asks if no name is given)")
    add.add_argument("name", nargs="?", help="letters, numbers and underscores, e.g. priority")
    add.add_argument("label", nargs="?", help="display label, e.g. Priority")
    add.set_defaults(func=cmd_fields_add)
    rename = field_commands.add_parser("rename", help="change a custom field's label (pick from a list)")
    rename.add_argument("name", nargs="?")
    rename.add_argument("label", nargs="?")
    rename.set_defaults(func=cmd_fields_rename)
    delete = field_commands.add_parser("delete", help="delete a custom field (pick from a list)")
    delete.add_argument("name", nargs="?")
    delete.set_defaults(func=cmd_fields_delete)

    args = parser.parse_args()
    try:
        args.func(args)
    except ApiError as e:
        sys.exit(f"Error: {e}")
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nCancelled.")
