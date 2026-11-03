"""Command line interface: parses commands, prompts the user, prints results."""

import argparse
import getpass
import sys

from ticketforge.client import ApiError, TicketForgeClient
from ticketforge.config import CONFIG_PATH, save_config


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


def main():
    parser = argparse.ArgumentParser(prog="ticketforge", description="Manage TicketForge tickets from the terminal.")
    commands = parser.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="connect to TicketForge and save your credentials")
    setup.set_defaults(func=cmd_setup)

    args = parser.parse_args()
    try:
        args.func(args)
    except ApiError as e:
        sys.exit(f"Error: {e}")
