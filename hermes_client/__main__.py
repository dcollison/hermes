"""Entry point for `python -m hermes_client`.
Delegates to the same CLI as the `hermes-client` console script.
"""

# Remote
from hermes_client.cli import main

if __name__ == "__main__":
    main()
