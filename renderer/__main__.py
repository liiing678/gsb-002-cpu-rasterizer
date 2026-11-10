"""Public command interface; implement the rendering pipeline here or in modules."""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Render a scene on the CPU")
    parser.add_argument("--scene", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, choices=(1, 4), default=4)
    parser.parse_args()
    parser.exit(2, "Rendering pipeline is not implemented. See contract.md.\n")


if __name__ == "__main__":
    main()
