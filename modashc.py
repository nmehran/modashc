import argparse
import json
import sys
from methods.compile import compile_sources
from methods.source_resolver import UnsupportedSourceError


def main(entry_point, output_file, mode="context", source_supplement=None):
    compile_sources(entry_point, output_file, mode=mode, source_supplement=source_supplement)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Merge Bash scripts into a single script.')
    parser.add_argument('entrypoint', type=str, help='The entry-point Bash script that initiates the merging process.')
    parser.add_argument('output', type=str, help='The output file where the merged script will be saved.')
    parser.add_argument(
        '--mode',
        choices=('context', 'executable'),
        default='context',
        help='Output mode. context is readable-first; executable preserves Bash source execution behavior.',
    )
    parser.add_argument(
        '--source-supplement',
        help='JSON file with exact source-relevant values for runtime-dynamic source sites.',
    )
    args = parser.parse_args()
    try:
        main(
            entry_point=args.entrypoint,
            output_file=args.output,
            mode=args.mode,
            source_supplement=args.source_supplement,
        )
    except UnsupportedSourceError as exc:
        print(f"modashc: {exc}", file=sys.stderr)
        details = exc.diagnostic.details if exc.diagnostic is not None else exc.details
        skeleton = details.get("supplement_skeleton") if details else None
        if skeleton:
            print("modashc: source supplement skeleton:", file=sys.stderr)
            print(json.dumps(skeleton, indent=2, sort_keys=True), file=sys.stderr)
        sys.exit(1)
