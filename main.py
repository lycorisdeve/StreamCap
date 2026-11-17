"""StreamCap executable entry point; no application imports before ownership."""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from launcher import launch

    raise SystemExit(launch())
