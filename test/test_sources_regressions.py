import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from methods.sources import get_commands, get_sources
from test.support import ScriptProject


class SourceRegressionTestCase(unittest.TestCase):
    def test_get_commands_keeps_hash_inside_words_and_paths(self):
        self.assertEqual(
            list(get_commands('echo foo#bar; source dep.sh')),
            ['echo foo#bar', 'source dep.sh'],
        )
        self.assertEqual(
            list(get_commands('source ./dir#1/dep.sh; echo done')),
            ['source ./dir#1/dep.sh', 'echo done'],
        )
        self.assertEqual(
            list(get_commands('echo foo # comment; source dep.sh')),
            ['echo foo'],
        )

    def test_get_commands_ignores_quoted_separators_and_comments(self):
        self.assertEqual(
            list(get_commands('echo "a;b"; source file.sh')),
            ['echo "a;b"', 'source file.sh'],
        )
        self.assertEqual(
            list(get_commands('echo "not # comment"; source file.sh # trailing')),
            ['echo "not # comment"', 'source file.sh'],
        )
        self.assertEqual(
            list(get_commands('echo "a&&b"; source file.sh')),
            ['echo "a&&b"', 'source file.sh'],
        )

    def test_get_commands_splits_top_level_logical_operators(self):
        self.assertEqual(
            list(get_commands('cd subdir && source ./dep.sh || echo missing')),
            ['cd subdir', 'source ./dep.sh', 'echo missing'],
        )

    def test_command_wrapped_source_is_detected_as_source_command(self):
        from methods.source_resolver import contains_source_command

        self.assertTrue(contains_source_command('command source ./dep.sh'))
        self.assertTrue(contains_source_command('command -p source ./dep.sh'))
        self.assertTrue(contains_source_command('command -- source ./dep.sh'))
        self.assertTrue(contains_source_command('builtin source ./dep.sh'))
        self.assertTrue(contains_source_command('FOO=bar source ./dep.sh'))
        self.assertTrue(contains_source_command('FOO=bar command source ./dep.sh'))
        self.assertTrue(contains_source_command('helper(){ source ./dep.sh'))
        self.assertTrue(contains_source_command('function helper { source ./dep.sh'))
        self.assertFalse(contains_source_command('command echo source ./dep.sh'))
        self.assertFalse(contains_source_command('command -v source'))
        self.assertFalse(contains_source_command('command -V source'))
        self.assertFalse(contains_source_command('FOO=bar echo source ./dep.sh'))

    def test_heredoc_detection_ignores_quotes_and_arithmetic(self):
        from methods.source_resolver import extract_heredoc_delimiters

        self.assertEqual([item.value for item in extract_heredoc_delimiters('cat <<EOF')], ['EOF'])
        self.assertEqual([item.value for item in extract_heredoc_delimiters("cat <<'EOF'")], ['EOF'])
        self.assertEqual(extract_heredoc_delimiters('echo "<<EOF"'), [])
        self.assertEqual(extract_heredoc_delimiters('echo $((1 << 2))'), [])
        self.assertEqual(extract_heredoc_delimiters('(( value << 2 ))'), [])

    def test_static_source_discovery_matrix(self):
        with ScriptProject() as project:
            absolute_dep = project.write("absolute.sh", 'echo "absolute"\n')
            project.write("dep.sh", 'echo "relative"\n')
            project.write("dot.sh", 'echo "dot"\n')
            project.write("dir with spaces/dep.sh", 'echo "spaces"\n')
            project.write("dir#tag/dep.sh", 'echo "hash"\n')
            project.write("config", 'echo "config"\n')
            project.write("main.sh", "\n".join([
                "source ./dep.sh",
                ". ./dot.sh",
                'source "./dir with spaces/dep.sh"',
                'source "./dir#tag/dep.sh"',
                "source ./config",
                f'source "{absolute_dep}"',
                "",
            ]))

            project.assert_sources(self, "main.sh", [
                "dep.sh",
                "dot.sh",
                "dir with spaces/dep.sh",
                "dir#tag/dep.sh",
                "config",
                "absolute.sh",
                "main.sh",
            ])

    def test_get_sources_does_not_mutate_process_cwd(self):
        with ScriptProject() as project:
            project.write("dir1/dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", 'cd dir1\nsource ./dep.sh\n')

            before = os.getcwd()
            try:
                get_sources(str(entry))
                after = os.getcwd()
            finally:
                os.chdir(before)

        self.assertEqual(after, before)

    def test_relative_source_resolution_does_not_fall_back_to_process_cwd(self):
        before = os.getcwd()
        with ScriptProject() as project:
            project.write("caller/dep.sh", 'echo "wrong cwd dependency"\n')
            project.write("script/main.sh", 'source ./dep.sh\n')

            try:
                os.chdir(project.path("caller"))
                actual = [
                    path.relative_to(project.root).as_posix()
                    for path in project.sources("script/main.sh", mode="context")
                ]
            finally:
                os.chdir(before)

        self.assertEqual(actual, ["script/main.sh"])

    def test_sample_dir_discovery_graph_stays_explicit(self):
        before = os.getcwd()
        try:
            actual_sources, _ = get_sources(str(REPO_ROOT / "test" / "sample_dir" / "script_main.sh"))
            entry_directory = REPO_ROOT / "test" / "sample_dir"
            actual = [Path(path).relative_to(entry_directory).as_posix() for path in actual_sources]
        finally:
            os.chdir(before)

        self.assertEqual(actual, [
            "dir1/script6.sh",
            "script5.sh",
            "script4.sh",
            "dir with spaces/script3.sh",
            "dir2/script2.sh",
            "dir1/script1.sh",
            "script_main.sh",
        ])


if __name__ == "__main__":
    unittest.main()
