# This file is part of HDL Code Checker.
#
# HDL Code Checker is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# HDL Code Checker is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with HDL Code Checker.  If not, see <http://www.gnu.org/licenses/>.

# pylint: disable=function-redefined, missing-docstring, protected-access

import os
import os.path as p
import time
import logging

from nose2.tools import such

import hdlcc
from hdlcc.tests.utils import writeListToFile

_logger = logging.getLogger(__name__)

BUILDER_NAME = os.environ.get('BUILDER_NAME', None)
BUILDER_PATH = p.expandvars(os.environ.get('BUILDER_PATH', \
                            p.expanduser("~/ghdl/bin/")))

HDL_LIB_PATH = p.join(".ci", "hdl_lib")

if BUILDER_NAME is not None:
    PROJECT_FILE = p.join(HDL_LIB_PATH, BUILDER_NAME + '.prj')
else:
    PROJECT_FILE = None

from multiprocessing import Queue

class StandaloneProjectBuilder(hdlcc.ProjectBuilder):
    "Class for testing ProjectBuilder"
    _msg_queue = Queue()
    _ui_handler = logging.getLogger('UI')
    def __init__(self):
        super(StandaloneProjectBuilder, self).__init__(PROJECT_FILE)

    def _handleUiInfo(self, message):
        self._msg_queue.put(('info', message))
        self._ui_handler.info(message)

    def _handleUiWarning(self, message):
        self._msg_queue.put(('warning', message))
        self._ui_handler.warning(message)

    def _handleUiError(self, message):
        self._msg_queue.put(('error', message))
        self._ui_handler.error(message)

with such.A('hdlcc test using hdl_lib') as it:

    it.DUMMY_PROJECT_FILE = p.join(os.curdir, 'remove_me')

    @it.has_setup
    def setup():
        it.assertIn(os.name, ('nt', 'posix'))
        StandaloneProjectBuilder.clean(PROJECT_FILE)

    @it.has_teardown
    def teardown():
        StandaloneProjectBuilder.clean(PROJECT_FILE)
        if p.exists(it.DUMMY_PROJECT_FILE):
            os.removedirs(it.DUMMY_PROJECT_FILE)

    with it.having('a valid project file'):

        with it.having('a valid environment'):

            @it.has_setup
            def setup():
                hdlcc.ProjectBuilder.clean(PROJECT_FILE)

                it.builder_env = os.environ.copy()

                if os.name == 'posix':
                    it.builder_env['PATH'] = \
                        os.pathsep.join([BUILDER_PATH, it.builder_env['PATH']])
                elif os.name == 'nt':
                    os.putenv('PATH',
                              os.pathsep.join([BUILDER_PATH, it.builder_env['PATH']]))

                _logger.info("Builder env path:")
                for path in it.builder_env['PATH'].split(os.pathsep):
                    _logger.info(" >'%s'", path)

                builder = hdlcc.builders.getBuilderByName(BUILDER_NAME)

                if os.environ.get('CI', '') == 'true' and \
                        BUILDER_NAME is not None:
                    with it.assertRaises(hdlcc.exceptions.SanityCheckError):
                        builder(it.DUMMY_PROJECT_FILE)

                it.original_env = os.environ.copy()
                os.environ = it.builder_env.copy()

                try:
                    builder(it.DUMMY_PROJECT_FILE)
                except hdlcc.exceptions.SanityCheckError:
                    it.fail("Builder creation failed even after configuring "
                            "the builder path")

            @it.has_teardown
            def teardown():
                hdlcc.ProjectBuilder.clean(PROJECT_FILE)
                os.environ = it.original_env.copy()
                del it.project

            @it.should('build project by dependency in background')
            def test_001(case):
                _logger.info("Creating project builder object")
                it.project = StandaloneProjectBuilder()
                _logger.info("Checking if msg queue is empty")
                if PROJECT_FILE is None:
                    _logger.warning("Skipping '%s'", case)
                    return
                it.assertTrue(it.project._msg_queue.empty())
                it.assertFalse(it.project.finishedBuilding())

            @it.should('notify if a build is already running')
            def test_002(case):
                if PROJECT_FILE is None:
                    _logger.warning("Skipping '%s'", case)
                    return
                it.project.buildByDependency()
                while it.project._msg_queue.empty():
                    time.sleep(0.1)
                messages = []
                while not it.project._msg_queue.empty():
                    messages.append(it.project._msg_queue.get())

                try:
                    it.assertIn(('info', 'Build thread is already running'),
                                messages)
                except:
                    it.project.waitForBuild()
                    raise

            @it.should('warn when trying to build a source before the build '
                       'thread completes')
            def test_003(case):
                if PROJECT_FILE is None:
                    _logger.warning("Skipping '%s'", case)
                    return
                filename = p.join(HDL_LIB_PATH, 'memory', 'testbench',
                                  'async_fifo_tb.vhd')

                it.assertTrue(it.project._msg_queue.empty())

                it.project.getMessagesByPath(filename)

                for _ in range(50):
                    if it.project._msg_queue.empty():
                        break
                    time.sleep(0.1)

                messages = []
                while not it.project._msg_queue.empty():
                    messages.append(it.project._msg_queue.get())

                try:
                    it.assertIn(('warning', "Project hasn't finished building, "
                                            "try again after it finishes."),
                                messages)
                except:
                    it.project.waitForBuild()
                    raise

                it.project.waitForBuild()

            @it.should('wait until build has finished')
            def test_004():
                it.project.waitForBuild()

            @it.should('get messages by path')
            def test_005():
                filename = p.join(HDL_LIB_PATH, 'memory', 'testbench',
                                  'async_fifo_tb.vhd')

                it.assertTrue(it.project._msg_queue.empty())

                records = it.project.getMessagesByPath(filename)

                it.assertIn(
                    {'error_subtype' : 'Style',
                     'line_number'   : 29,
                     'checker'       : 'HDL Code Checker/static',
                     'error_message' : "constant 'ADDR_WIDTH' is never used",
                     'column'        : 14,
                     'error_type'    : 'W',
                     'error_number'  : '0',
                     'filename'      : None},
                    records)

                it.assertTrue(it.project._msg_queue.empty())

            @it.should('get updated messages')
            def test_006():
                filename = p.join(HDL_LIB_PATH, 'memory', 'testbench',
                                  'async_fifo_tb.vhd')

                it.assertTrue(it.project._msg_queue.empty())

                code = open(filename, 'r').read().split('\n')

                code[28] = '-- ' + code[28]

                writeListToFile(filename, code)

                records = it.project.getMessagesByPath(filename)

                try:
                    it.assertNotIn(
                        {'error_subtype' : 'Style',
                         'line_number'   : 29,
                         'checker'       : 'HDL Code Checker/static',
                         'error_message' : "constant 'ADDR_WIDTH' is never used",
                         'column'        : 14,
                         'error_type'    : 'W',
                         'error_number'  : '0',
                         'filename'      : None},
                        records)
                finally:
                    # Remove the comment we added
                    code[28] = code[28][3:]
                    writeListToFile(filename, code)

                it.assertTrue(it.project._msg_queue.empty())

            @it.should('get messages by path of a different source')
            def test_007(case):
                if PROJECT_FILE is None:
                    _logger.warning("Skipping '%s'", case)
                    return
                filename = p.join(HDL_LIB_PATH, 'memory', 'async_fifo.vhd')

                it.assertTrue(it.project._msg_queue.empty())

                records = it.project.getMessagesByPath(filename)

                it.assertTrue(len(records) == 0)

                it.assertTrue(it.project._msg_queue.empty())

            @it.should('get updated messages of a different source')
            def test_008():
                if BUILDER_NAME is None:
                    return

                filename = p.join(HDL_LIB_PATH, 'memory', 'async_fifo.vhd')
                it.assertTrue(it.project._msg_queue.empty())

                code = open(filename, 'r').read().split('\n')

                _logger.info("Commenting line 28 should yield an error")
                _logger.info(repr(code[28]))

                code[28] = '-- ' + code[28]

                writeListToFile(filename, code)

                records = it.project.getMessagesByPath(filename)

                try:
                    it.assertNotEquals(records, [])
                finally:
                    # Remove the comment we added
                    code[28] = code[28][3:]
                    writeListToFile(filename, code)

                it.assertTrue(it.project._msg_queue.empty())

            @it.should('rebuild sources when needed within the same library')
            def test_009():
                if BUILDER_NAME is None:
                    return

                # Count how many messages each source has
                source_msgs = {}

                for filename in (
                        p.join(HDL_LIB_PATH, 'common_lib', 'sr_delay.vhd'),
                        p.join(HDL_LIB_PATH, 'common_lib', 'edge_detector.vhd')):

                    _logger.info("Getting messages for '%s'", filename)
                    source_msgs[filename] = \
                        it.project.getMessagesByPath(filename)

                _logger.info("Changing common_pkg to force rebuilding "
                             "synchronizer and another one I don't recall "
                             "right now")
                common_pkg = p.join(HDL_LIB_PATH, 'common_lib',
                                    'common_pkg.vhd')

                code = open(common_pkg, 'r').read().split('\n')

                writeListToFile(common_pkg,
                                code[:9] + \
                                ["    constant TESTING : integer := 4;"] + \
                                code[9:])

                # The number of messages on all sources should not change
                it.assertEquals(it.project.getMessagesByPath(common_pkg), [])

                for filename in (
                        p.join(HDL_LIB_PATH, 'common_lib', 'sr_delay.vhd'),
                        p.join(HDL_LIB_PATH, 'common_lib', 'edge_detector.vhd')):

                    if source_msgs[filename]:
                        _logger.info("Source %s had the following messages:\n%s",
                                     filename,
                                     "\n".join([str(x) for x in
                                                source_msgs[filename]]))
                    else:
                        _logger.info("Source %s has no previous messages",
                                     filename)

                    it.assertEquals(source_msgs[filename],
                                    it.project.getMessagesByPath(filename))

                _logger.info("Restoring previous content")
                writeListToFile(common_pkg, code)

            @it.should('rebuild sources when needed for different libraries')
            def test_010():
                if BUILDER_NAME is None:
                    return

                # Count how many messages each source has
                source_msgs = {}

                for filename in (
                        p.join(HDL_LIB_PATH, 'common_lib', 'sr_delay.vhd'),
                        p.join(HDL_LIB_PATH, 'memory', 'ram_inference.vhd')):

                    _logger.info("Getting messages for '%s'", filename)
                    source_msgs[filename] = \
                        it.project.getMessagesByPath(filename)

                _logger.info("Changing common_pkg to force rebuilding "
                             "synchronizer and another one I don't recall "
                             "right now")
                common_pkg = p.join(HDL_LIB_PATH, 'common_lib',
                                    'common_pkg.vhd')

                code = open(common_pkg, 'r').read().split('\n')

                writeListToFile(common_pkg,
                                code[:9] + \
                                ["    constant ANOTHER_TEST_NOW : integer := 1;"] + \
                                code[9:])

                # The number of messages on all sources should not change
                it.assertEquals(it.project.getMessagesByPath(common_pkg), [])

                for filename in (
                        p.join(HDL_LIB_PATH, 'common_lib', 'sr_delay.vhd'),
                        p.join(HDL_LIB_PATH, 'memory', 'ram_inference.vhd')):

                    if source_msgs[filename]:
                        _logger.info("Source %s had the following messages:\n%s",
                                     filename,
                                     "\n".join([str(x) for x in
                                                source_msgs[filename]]))
                    else:
                        _logger.info("Source %s has no previous messages",
                                     filename)

                    it.assertEquals(source_msgs[filename],
                                    it.project.getMessagesByPath(filename))

                _logger.info("Restoring previous content")
                writeListToFile(common_pkg, code)

                #  try:
                #      it.assertNotEquals(records, [])
                #  finally:
                #      # Remove the comment we added
                #      code[28] = code[28][3:]
                #      writeListToFile(filename, code)

                #  it.assertTrue(it.project._msg_queue.empty())

        #      @it.should("warn when a source wasn't found in the project file")
        #      def test_010():
        #          test_path = p.abspath('file_outside_the_prj_file.vhd')
        #          expected_msg = 'Path "%s" not found in project file' % test_path
        #          if not p.exists(test_path):
        #              open(test_path, 'w').close()
        #          records = it.project.getMessagesByPath(\
        #              p.expanduser(test_path))

        #          found = False
        #          for record in records:
        #              if record['error_type'] == 'W' and \
        #                      record['error_message'] == expected_msg:
        #                  found = True
        #                  break

        #          it.assertTrue(found, "File not found error not found")

        #      @it.should("find source containing a given design unit")
        #      def test_011():
        #          sources = it.project._findSourceByDesignUnit("another_library.foo")
        #          it.assertTrue(len(sources) == 1, "Should find a single source "
        #                                           "but found %d" % len(sources))
        #          source = sources.pop()
        #          it.assertIsInstance(source, hdlcc.source_file.VhdlSourceFile, \
        #              "Source file returned is not an instance of "
        #              "hdlcc.source_file.VhdlSourceFile")

        #          it.assertEqual(source.library, "another_library", \
        #              "Source file library '%s' is not 'another_library" % source.library)

        #          it.assertEqual(source.filename, \
        #              p.abspath(".ci/vim-hdl-examples/"
        #                        "another_library/foo.vhd"))

        #      @it.should("fail to find source containing a non-existing design unit")
        #      def test_012():
        #          sources = it.project._findSourceByDesignUnit("foo_bar.foo")
        #          it.assertTrue(len(sources) == 0, "Should not find any source!")

        #      @it.should("clean up generated files")
        #      def test_013():
        #          #  cache_fname = StandaloneProjectBuilder._getCacheFilename(PROJECT_FILE)
        #          #  it.assertTrue(p.exists(cache_fname),
        #          #                "Cache file '%s' not found" % cache_fname)

        #          #  cache_folder = it.project.builder._target_folder

        #          #  it.assertTrue(p.exists(cache_folder),
        #          #                "Cache folder '%s' not found" % cache_folder)

        #          # Do this twice to check that the project builder doesn't
        #          # fails if we try to clean up more than once
        #          for _ in range(2):
        #              StandaloneProjectBuilder.clean(PROJECT_FILE)

        #              #  it.assertFalse(p.exists(cache_fname),
        #              #                 "Cache file '%s' still exists" % cache_fname)

        #              #  #  it.assertFalse(p.exists(cache_folder),
        #              #  #                 "Cache folder '%s' still exists" % cache_folder)

it.createTests(globals())

