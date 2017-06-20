# Contents Copyright Shanghai ShanCe Technologies Company Ltd. All Rights Reserved.

from __future__ import with_statement

import SCons
import shutil
import atexit
import copy
import datetime
import errno
import math
import os
import platform
import re
import socket
import subprocess
import sys
import time
import uuid
import pprint
import protoc

from collections import defaultdict
from threading import BoundedSemaphore

ACR_CompilerDefault = 'gcc'

# base compiler options
compiler_base = {
    'cc'      : 'gcc',
    'cxx'     : 'g++',
    'link'    : 'g++',
    'shlink'  : 'g++',

    # Flags that are applied on all build types
    'flags' : {
        'cppdefines' : [ 'MYSQLPP_MYSQL_HEADERS_BURIED', ('DEB_HOST_MULTIARCH', '\\"x86_64-linux-gnu\\"') ],
        'cc'         : [ '-pthread', '-Wall', '-Werror', '-Wno-error=deprecated-declarations' ],
        'shcc'       : [ '-fPIC' ],
        'cxx'        : [ '-Woverloaded-virtual', '-Wnon-virtual-dtor', '-fvisibility-inlines-hidden' ],
        'link'       : [ '-Wl,--fatal-warnings', '-Wl,--no-undefined', '-Wl,-z,origin' ],
        'shlink'     : [ '-shared' ],
        },

    # Flags that are applied only on optimized builds
    'opt_flags' : {
        'cppdefines' : [ 'NDEBUG' ],
        'cc'         : [ '-O3', '-msse3', '-ftree-vectorize' ],
        },

    # Flags that are applied only on non-optimized builds
    'nopt_flags' : {},

    # Flags that are applied only on debug builds
    'dbg_flags' : {
        'cc' : [ '-g' ],
        },

    # Flags that are applied only on ndebug builds
    'ndbg_flags' : {
        'cppdefines' : [ 'NDEBUG' ],
        },

    'arc_flags' : {
        'cc' : ['-fprofile-generate'],
        },

    'cov_flags'  : {
        'cc' : ['--coverage']
        },

    'guess_flags': {
        'cc' : ['-fprofile-use'],
        },

    'backtrace_flags': {
        'cc' : ['-fno-omit-frame-pointer']
        },

    'experimental_flags' : {
        'cxx' : ['-std=c++11', '-I/usr/local/boost/1_55_c++11', '-Wno-deprecated', '-Wno-error=unused-variable'],
        'link' : ['-L/usr/local/boost/1_55_c++11/lib/'],
        },

    'ubuntu14_flags' : {
        # Sadly, gcc 4.8 is a memory hog; in order to reduce memory consumption
        # we give up diagnostic information (only when the compiler encounters)
        # errors in pre-processor macros
        # https://gcc.gnu.org/bugzilla/show_bug.cgi?id=56746
        'cc' : ['-ftrack-macro-expansion=0'],
        'cppdefines' : [ 'UBUNTU', 'UBUNTU14', 'HAVE_CSTDDEF' ],
        },

    'ubuntu12_flags' : {
        'cppdefines' : [ 'UBUNTU', 'UBUNTU12' ],
        },

    'centos7_flags' : {
        'cppdefines' : [ 'CENTOS', 'CENTOS7', 'HAVE_CONFIG_H' ],
        'cc' : ['-Wno-narrowing', '-Wno-error=unused-local-typedefs', '-Wno-error=unused-variable' ],
        'link' : ['-L/usr/lib64/mysql'],
        },

    'centos6_flags' : {
        'cppdefines' : [ 'CENTOS', 'CENTOS6', 'HAVE_CONFIG_H' ],
        'cc' : ['-I/usr/include/boost148', '-Wno-deprecated', '-Wno-error=unused-variable'],
        'link' : ['-L/usr/lib64/boost148', '-L/usr/lib64/mysql'],
        },

    'step_logging_flags' : {
        'cppdefines' : [ 'STEP_LOGGING_ENABLED']
        },

    'suppress_stdout_flags' : {
        'cppdefines' : [ 'SUPPRESS_STDOUT']
        },

}

# setup gcc on top of gcc base
gcc_compiler = copy.deepcopy(compiler_base)
gcc_compiler['opt_flags']['cc'].append('-ftree-vectorize')

# setup clang on top of gcc base
clang_compiler = copy.deepcopy(compiler_base)
clang_compiler['cc'] = 'clang'
clang_compiler['cxx'] = 'clang++'
clang_compiler['link'] = 'clang++'
clang_compiler['shlink'] = 'clang++'
clang_compiler['flags']['cc'].append('-Wno-error=format-extra-args')
clang_compiler['flags']['cc'].append('-I/usr/include/x86_64-linux-gnu')
clang_compiler['flags']['cxx'].append('-Wno-error=c++0x-extensions')
clang_compiler['flags']['cxx'].append('-I/usr/include/x86_64-linux-gnu')

# map compiler names to their options
ACR_CompilerOptions = {
    'gcc'   : gcc_compiler,
    'clang' : clang_compiler
}

DEFAULT_PATH = '/with/bb/root'

# Alphabetized list of local options definitions.

SCons.Script.Main.AddOption('--arcs',
                            dest = 'ACR_option_arcs',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Generate profiling data for PGO [default: %default]')

SCons.Script.Main.AddOption('--backtrace',
                            dest = 'ACR_option_backtrace',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Compile with frame pointers enabled [default: %default]')

SCons.Script.Main.AddOption('--client-build',
                            dest = 'ACR_option_client_build',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Client build (same as specifying --no-gui --no-servers --no-web) [default: %default]')

SCons.Script.Main.AddOption('--copyright-holder',
                            dest = 'ACR_option_copyright_holder',
                            type = 'string',
                            action = 'store',
                            default = "",
                            help = 'Set the name of the ( default: "Shanghai ShanCe Technologies Company Ltd." )')

SCons.Script.Main.AddOption('--coverage',
                            dest = 'ACR_option_coverage',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Compile with coverage (gcov) enabled [default: %default]')

SCons.Script.Main.AddOption('--coverage-enable-lcov-targets',
                            dest = "ACR_option_coverage_enable_lcov_targets",
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Declare the lcov targets for HTML generation [default: %default]')

SCons.Script.Main.AddOption('--dump-test-logs',
                            dest = 'ACR_option_dump_test_logs',
                            type = 'choice',
                            choices = ('none', 'failed', 'all'),
                            action = 'store',
                            default = 'failed',
                            metavar = 'CHOICE',
                            help = 'ACR: show detailed test logs for which tests [default: %default]')

SCons.Script.Main.AddOption('--enable-build-stamps',
                            dest = 'ACR_option_enable_build_stamps',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Generate build stamps and signature files [default: %default]')

SCons.Script.Main.AddOption('--experimental',
                            dest = 'ACR_option_experimental',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Compile with experimental features enabled [default: %default]')

SCons.Script.Main.AddOption('--failed-tests-dont-fail-build',
                            dest = 'ACR_option_failed_tests_dont_fail_build',
                            action = "store_true",
                            default = False,
                            help = 'ACR: Allow the build to pass even if unit tests fail [default: %default]')

SCons.Script.Main.AddOption('--guess',
                            dest = 'ACR_option_guess',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Use profiling data (from --arcs) for PGO [default: %default]')

SCons.Script.Main.AddOption('--gui',
                            dest = 'ACR_option_gui',
                            action = 'store_true',
                            default = True,
                            help = 'ACR: build/install GUI components')

SCons.Script.Main.AddOption('--icecc',
                            dest = 'ACR_option_icecc',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Use icecc for parallel builds [default: %default]')

SCons.Script.Main.AddOption('--luajit',
                            dest = 'ACR_option_luajit',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Build with LuaJIT2 linked and enabled [default: %default]')

SCons.Script.Main.AddOption('--max-test-concurrency',
                            dest = 'ACR_option_max_test_concurrency',
                            type = 'int',
                            action = 'store',
                            default = None,
                            metavar = 'LIMIT',
                            help = 'ACR: upper bound on concurrent tests (0 for autodetect) [default: %default]')

SCons.Script.Main.AddOption('--ndebug',
                            dest = 'ACR_option_ndebug',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Compile without debugging symbols and assertions [default: %default]')

SCons.Script.Main.AddOption('--no-defer-test-execution',
                            dest = "ACR_option_no_defer_test_execution",
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Allow tests to run when ready, not only at end of build [default: %default]')

SCons.Script.Main.AddOption('--no-gui',
                            dest = 'ACR_option_gui',
                            action = 'store_false',
                            default = True,
                            help = 'ACR: do not build/install GUI components')

SCons.Script.Main.AddOption('--no-servers',
                            dest = 'ACR_option_servers',
                            action = 'store_false',
                            default = True,
                            help = 'ACR: do not build/install server components')

SCons.Script.Main.AddOption('--no-tcmalloc',
                            dest = "ACR_option_no_tcmalloc",
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Do not use tcmalloc as the memory allocator [default: %default]')

SCons.Script.Main.AddOption('--no-tcmalloc-debug-features',
                            dest = 'ACR_option_no_tcmalloc_debug_features',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: for debug builds, disable tcmalloc debugging features [default: %default]')

SCons.Script.Main.AddOption('--no-web',
                            dest = 'ACR_option_web',
                            action = 'store_false',
                            default = True,
                            help = 'ACR: do not build/install web components')

SCons.Script.Main.AddOption('--opt',
                            dest = 'ACR_option_opt',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Compile with optimizations enabled [default: %default]')

SCons.Script.Main.AddOption('--install-dir',
                            dest = 'ACR_option_install_dir',
                            type = 'string',
                            action = 'store',
                            default = DEFAULT_PATH,
                            help = 'Set the install dir ( default: %s )' % DEFAULT_PATH )

SCons.Script.Main.AddOption('--runs-per-test',
                            dest = 'ACR_option_runs_per_test',
                            type = 'int',
                            action = 'store',
                            default = 1,
                            metavar = 'ITERS',
                            help = 'ACR: iterations per test [default: %default]')

SCons.Script.Main.AddOption('--run-tests-under',
                            dest = 'ACR_option_run_tests_under',
                            type = 'string',
                            action = 'store',
                            default = None,
                            metavar = 'TOOL',
                            help = 'ACR: Comma separated list of test tags [default: %default]')

SCons.Script.Main.AddOption('--run-under-args',
                            dest = 'ACR_option_run_under_args',
                            type = 'string',
                            action = 'store',
                            default = str(),
                            metavar = 'ARGS',
                            help = 'ACR: Extra "quoted" arguments to TOOL [default: %default]')

SCons.Script.Main.AddOption('--run-performance-tests',
                            dest = 'ACR_option_run_performance_tests',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Run performance unit tests in addition to standard unit tests [default: %default]')

SCons.Script.Main.AddOption('--servers',
                            dest = 'ACR_option_servers',
                            action = 'store_true',
                            default = True,
                            help = 'ACR: build/install server components')

SCons.Script.Main.AddOption('--step-logging',
                            dest = 'ACR_step_logging',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: log order trail step times')

SCons.Script.Main.AddOption('--suppress-stdout',
                            dest = 'ACR_suppress_stdout',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: disable logging to stdout')

SCons.Script.Main.AddOption('--strip-style',
                            dest = 'ACR_option_strip_style',
                            type = 'choice',
                            choices = ('none', 'debug', 'all'),
                            action = 'store',
                            default = 'all',
                            metavar = 'CHOICE',
                            help = 'ACR: strip binaries in various ways [default: %default]')

SCons.Script.Main.AddOption('--strip-no-stripfile',
                            dest = 'ACR_option_strip_no_stripfile',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: Don\'t make a .debug file with stripped debug info and/or symbols [default: %default]')

SCons.Script.Main.AddOption('--test-report-color',
                            dest = 'ACR_option_test_report_color',
                            action = 'store_true',
                            default = True,
                            help = 'ACR: Colorize final test report [default: %default]')

SCons.Script.Main.AddOption('--test-tags-filter',
                            dest = 'ACR_option_test_tags_filter',
                            type = 'string',
                            action = 'store',
                            default = 'all',
                            metavar = 'FILTERS',
                            help = 'ACR: Comma separated list of test tags [default: %default]')

SCons.Script.Main.AddOption('--test-timeout-scale-factor',
                            dest = 'ACR_option_test_timeout_scale_factor',
                            type = 'int',
                            action = 'store',
                            default = 1,
                            metavar = 'FACTOR',
                            help = 'ACR: Scale factor for test timeouts [default: %default]')

SCons.Script.Main.AddOption('--test-timeout-signal',
                            dest = 'ACR_option_test_timeout_signal',
                            type = 'int',
                            action = 'store',
                            default = 9, # SIGKILL
                            metavar = 'SIGNAL',
                            help = 'ACR: signal with which to kill timed-out tests [default: %default]')

SCons.Script.Main.AddOption('--toolchain',
                            dest = 'ACR_option_toolchain',
                            type = 'string',
                            default = ACR_CompilerDefault,
                            metavar = 'TOOLCHAIN',
                            help = 'ACR: Select a known toolchain [default: %default]')

SCons.Script.Main.AddOption('--clang-analyze',
                            dest = 'ACR_option_clang_analyze',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: use clang static analyzer [default: %default]')

SCons.Script.Main.AddOption('--verbose',
                            dest = 'ACR_option_verbose_targets',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: print verbose build steps [default: %default]')

SCons.Script.Main.AddOption('--web',
                            dest = 'ACR_option_web',
                            action = 'store_true',
                            default = True,
                            help = 'ACR: build/install web components')

SCons.Script.Main.AddOption('--java',
                            dest = 'ACR_option_java',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: build/install java components')

SCons.Script.Main.AddOption('--csharp',
                            dest = 'ACR_option_csharp',
                            action = 'store_true',
                            default = False,
                            help = 'ACR: do not build/install csharp components')

SCons.Script.Main.AddOption('--no-swig-java',
                            dest = 'ACR_option_swig_java',
                            action = 'store_false',
                            default = True,
                            help = 'ACR: skip building the swig Java support')

SCons.Script.Main.AddOption('--no-swig-python',
                            dest = 'ACR_option_swig_python',
                            action = 'store_false',
                            default = True,
                            help = 'ACR: skip building the swig Python support')

SCons.Script.Main.AddOption('--no-swig-ruby',
                            dest = 'ACR_option_swig_ruby',
                            action = 'store_false',
                            default = True,
                            help = 'ACR: skip building the swig Ruby support')

# make a dummy 'tests' target
# this allows scons to not fail on a 'tests' target
# when one tries to build it.
# programs can override this if they need to
SCons.Defaults.DefaultEnvironment().Alias('tests', '')

class SymlinkHelpers:
    @staticmethod
    def string_it(target, source, env):
        return "symlinking " + str(target[0]) + " to " + str(source[0])

    @staticmethod
    def build_it(target, source, env):
        if not os.path.exists(str(target[0])):
            os.symlink(str(source[0]), str(target[0]))

class BuildEnv(object):

    @classmethod
    def MakeTree( klass, ARGLIST, Environment, root, module, ignorelist=[] ):

        # Try to protect against running an sconstruct file if this is
        # an embedded tree. This isn't perfect: symlinks for instance
        # will foil it. However, it is some protection, and if you are
        # symlinking repos...
        if root.Dir('..').File('sconstruct').exists():
            raise RuntimeError, "A parent sconstruct exists in '..', refusing to build from here."

        rootDir = root.path

        dirlist = [ f for f in os.listdir(rootDir) if os.path.isdir(os.path.join(rootDir, f)) and not f.startswith('.') ]
        scriptDirs = []
        ignored_roots = []
        for curDir in [os.path.join(rootDir, i) for i in dirlist]:
            for subDir, dirs, files in os.walk(curDir):
                # any subdirectory of a direcotory that contains an 'ignore file' will also be ignored.
                # for instance, by default we ignore all 'jadedragon' sub-directories once we find a '.scons_ignore' file
                # in the root
                ignore = any([x for x in ignored_roots if str(subDir).startswith(x)])
                for i in ignorelist:
                    if subDir.find(i) != -1 or os.path.isfile(os.path.join(subDir, i)):
                        ignored_roots.append(subDir)
                        ignore = True
                        break

                if not ignore and 'sconscript' in files:
                    scriptDirs += [subDir]

        scriptDirs.append(rootDir)
        acr = BuildEnv(ARGLIST, Environment)
        SCons.Script.Export(['acr'])

        SCons.Script.SConsignFile(acr.bb_build_root.File('sconsign').abspath)

        for i in scriptDirs:
            buildDir = acr.buildFlavaDir.Dir(module).Dir(i)
            SCons.Script.SConscript(dirs=i, name='sconscript', variant_dir=buildDir, duplicate=1)

        acr.finalize()
        return acr

    def __init__(self, arglist, Environment):

        # capture argument results so we can tweak them if we need.
        self.arcs                         = SCons.Script.Main.GetOption('ACR_option_arcs')
        self.backtrace                    = SCons.Script.Main.GetOption('ACR_option_backtrace')
        self.client_build                 = SCons.Script.Main.GetOption('ACR_option_client_build')
        self.copyright_holder             = SCons.Script.Main.GetOption('ACR_option_copyright_holder')
        self.coverage                     = SCons.Script.Main.GetOption('ACR_option_coverage')
        self.coverage_enable_lcov_targets = SCons.Script.Main.GetOption('ACR_option_coverage_enable_lcov_targets')
        self.dump_test_logs               = SCons.Script.Main.GetOption('ACR_option_dump_test_logs')
        self.enable_build_stamps          = SCons.Script.Main.GetOption('ACR_option_enable_build_stamps')
        self.experimental                 = SCons.Script.Main.GetOption('ACR_option_experimental')
        self.failed_tests_dont_fail_build = SCons.Script.Main.GetOption('ACR_option_failed_tests_dont_fail_build')
        self.guess                        = SCons.Script.Main.GetOption('ACR_option_guess')
        self.gui                          = SCons.Script.Main.GetOption('ACR_option_gui')
        self.icecc                        = SCons.Script.Main.GetOption('ACR_option_icecc')
        self.luajit                       = SCons.Script.Main.GetOption('ACR_option_luajit')
        self.max_test_concurrency         = SCons.Script.Main.GetOption('ACR_option_max_test_concurrency')
        self.ndebug                       = SCons.Script.Main.GetOption('ACR_option_ndebug')
        self.no_defer_test_execution      = SCons.Script.Main.GetOption('ACR_option_no_defer_test_execution')
        self.no_tcmalloc                  = SCons.Script.Main.GetOption('ACR_option_no_tcmalloc')
        self.no_tcmalloc_debug_features   = SCons.Script.Main.GetOption('ACR_option_no_tcmalloc_debug_features')
        self.optimize                     = SCons.Script.Main.GetOption('ACR_option_opt')
        self.install_dir                  = SCons.Script.Main.GetOption('ACR_option_install_dir')
        self.run_tests_under              = SCons.Script.Main.GetOption('ACR_option_run_tests_under')
        self.run_under_args               = SCons.Script.Main.GetOption('ACR_option_run_under_args').split()
        self.run_performance_tests        = SCons.Script.Main.GetOption('ACR_option_run_performance_tests')
        self.runs_per_test                = SCons.Script.Main.GetOption('ACR_option_runs_per_test')
        self.servers                      = SCons.Script.Main.GetOption('ACR_option_servers')
        self.swig_java                    = SCons.Script.Main.GetOption('ACR_option_swig_java')
        self.swig_python                  = SCons.Script.Main.GetOption('ACR_option_swig_python')
        self.swig_ruby                    = SCons.Script.Main.GetOption('ACR_option_swig_ruby')
        self.step_logging                 = SCons.Script.Main.GetOption('ACR_step_logging')
        self.suppress_stdout              = SCons.Script.Main.GetOption('ACR_suppress_stdout')
        self.strip_style                  = SCons.Script.Main.GetOption('ACR_option_strip_style')
        self.strip_no_stripfile           = SCons.Script.Main.GetOption('ACR_option_strip_no_stripfile')
        self.test_report_color            = SCons.Script.Main.GetOption('ACR_option_test_report_color')
        self.test_tags_filter             = SCons.Script.Main.GetOption('ACR_option_test_tags_filter')
        self.test_timeout_scale_factor    = SCons.Script.Main.GetOption('ACR_option_test_timeout_scale_factor')
        self.test_timeout_signal          = SCons.Script.Main.GetOption('ACR_option_test_timeout_signal')
        self.toolchain                    = SCons.Script.Main.GetOption('ACR_option_toolchain')
        self.clang_analyze                = SCons.Script.Main.GetOption('ACR_option_clang_analyze')
        self.verbose_targets              = SCons.Script.Main.GetOption('ACR_option_verbose_targets')
        self.web                          = SCons.Script.Main.GetOption('ACR_option_web')
        self.java                         = SCons.Script.Main.GetOption('ACR_option_java')
        self.csharp                       = SCons.Script.Main.GetOption('ACR_option_csharp')
        self.num_jobs                     = SCons.Script.Main.GetOption('num_jobs')

        # On Jul 28 2016, we replaced the onFill() callback and got rid of onFillWithFees. Older code would have
        # failed to compile with a compiler error about onFill but nothing about onFillWithFees. We want to prevent
        # a knightmare and will check once again that nobody is still trying to overload these callbacks.
        self.found_onFill = os.popen("find . -name '*.h'|xargs grep --binary-files=without-match -A2 -r \"onFill\\s*(\" | grep -v \"\.build\"|grep -v tests|awk 'NR % 3 !=0 {printf $0;printf \" \"} NR % 3 ==0 {print \" \"}'|grep -E \"OrderPtr.*double.*uint32\"").read().strip()
        self.found_onFillWithFees = os.popen("find . -name '*.h' | grep -v \".build\" | grep -v \".hg\" | grep -v ACR.pyc | grep -v tests | xargs grep --binary-files=without-match onFillWithFees").read().strip()
        if(len(self.found_onFill) != 0):
            print(self.found_onFill)
            raise RuntimeError, "Found code that looks like a deprecated onFill(OrderPtr, double, uint32_t) callback. Please amend your code to use onFill(const bb::trading::FillInfo& ) instead."
        if(len(self.found_onFillWithFees) != 0):
            print(self.found_onFillWithFees)
            raise RuntimeError, "Found code that looks like a deprecated onFillWithFees(OrderPtr, double, uint32_t, boost::optional<FeeInfo>& ) callback. Please amend your code to use onFill(const bb::trading::FillInfo& ) instead."

        if self.client_build:
            self.servers = False
            self.web = False
            self.gui = False
            self.java = False
            self.csharp = False

        self.centos = False
        self.centos6 = False
        self.centos7 = False
        self.ubuntu = False
        self.ubuntu12 = False
        self.ubuntu14 = False
        dist, ver_str, ident = platform.dist()
        ver_arr = re.split('\.', ver_str)
        if dist == 'centos':
            self.centos = True
            if ver_arr[0] == '6':
                self.centos6 = True
            elif ver_arr[0] == '7':
                self.centos7 = True
            else:
                raise RuntimeError, "Unkown CentOS version!"
        elif dist == 'Ubuntu':
            self.ubuntu = True
            if ver_arr[0] == '12':
                self.ubuntu12 = True
            elif ver_arr[0] == '14':
                self.ubuntu14 = True
            else:
                raise RuntimeError, "Unkown Ubuntu version!"
        else:
            raise RuntimeError, "Unkown distribution!"

        if self.experimental and not self.ubuntu14:
            raise RuntimeError, "c++11 is not supported on this OS version!"

        # FIXME: tcmalloc and lua don't play nice on Trusty, disabling tcmalloc
        # on Trusty for now (ACRUS-1640)
        if self.ubuntu14:
            self.no_tcmalloc = True

        # FIXME: when we combine tcmalloc and clang 3.4, we'll get warned that third-party Chinese APIs allocate
        # memory incorrectly. For instance libshfetraderapi.so:
        # ' memory allocation/deallocation mismatch at 0x5e4200: allocated with new [] being deallocated with delete '
        # This happens when running the unit test: 'jadedragon/servers/shfe/shfe_l2_qd/tests/test_shfe_l2_filter'.
        # We will 'resolve' this for now by disabling tcmalloc when building with clang.
        if self.toolchain == 'clang':
            self.no_tcmalloc = True

        self.local_libs = {}
        self.targets = []

        # Set a BB root
        self.bb_root = SCons.Script.Dir( DEFAULT_PATH )

        # get BB_BUILD_ROOT. Fall back to the old style ./.build
        # directory if it is not set.
        self.bb_build_root = os.environ.get('BB_BUILD_ROOT')
        if self.bb_build_root:
            self.bb_build_root = SCons.Script.Dir(self.bb_build_root)
        else:
            self.bb_build_root = SCons.Script.Dir('#').Dir('.build')

        if self.coverage_enable_lcov_targets and not self.coverage:
            print "Can't enable lcov targets for non-coverage build"
            sys.exit(1)

        # configure installation paths.
        self.install = SCons.Script.Dir( self.install_dir )

        self.include = self.install.Dir('include')
        self.lib = self.install.Dir('lib')
        self.bin = self.install.Dir('bin')
        self.testBin = self.bin.Dir('test')
        self.conf = self.install.Dir('conf')
        self.service = self.install.Dir('service')
        self.etc = self.install.Dir('etc')

        # platform information
        self.distro = os.popen('lsb_release -cs').read().strip()
        self.isLinux26 = (platform.platform().find('Linux-2.6') == 0)
        self.isAMD64 = (platform.machine() == 'x86_64')

        # only allow PATH in environment.
        self.env = { }
        self.env['PATH'] = os.environ['PATH'].split(os.pathsep)

        # For builds that are exposed to external entities, the copyright line
        # in the headers gets changed from "Shanghai ShanCe Technologies Company Ltd." to
        # whatever is in the environment variable BB_COPYRIGHT or the value of
        # the command line option --copyright-holder (the command line option
        # overrides the environment variable
        if (not self.copyright_holder or self.copyright_holder.isspace()) and 'BB_COPYRIGHT' in os.environ:
            self.copyright_holder = os.environ['BB_COPYRIGHT']

        if self.icecc and self.toolchain != 'clang':
            self.env['PATH'].insert(0, '/usr/lib/icecc/bin')
        elif self.icecc and self.toolchain == 'clang':
            print "Icecc + clang is currently unsupported. Compiling without icecc, and only using up to 30 cores."
            self.num_jobs = min(30, self.num_jobs)
        elif self.num_jobs > 30:
            raise RuntimeError, "You are building on the local PC only and have selected " + str ( self.num_jobs ) + " concurrent builds. That sounds dangerous and is not permitted. If you want to build quicker, enable the --icecc flag"

        # setup linkers, compilers, interpreters, and other programming tools
        if not self.toolchain in ACR_CompilerOptions:
            raise RuntimeError, ("I don't know about toolchain %s" % self.toolchain)
        options = ACR_CompilerOptions[self.toolchain]

        # get RUBY_HOME
        self.ruby_config = {}
        if self.centos7 or self.ubuntu14:
            self.ruby_config = {
                'arch': os.popen( "ruby -rrbconfig -e \"print RbConfig::CONFIG['arch']\" " ).read(),
                'archdir': os.popen( "ruby -rrbconfig -e \"print RbConfig::CONFIG['archdir']\" " ).read(),
                'hdrdir': os.popen( "ruby -rrbconfig -e \"print RbConfig::CONFIG['rubyhdrdir']\" " ).read(),
                'libdir': os.popen( "ruby -rrbconfig -e \"print RbConfig::CONFIG['libdir']\" " ).read(),
                'libruby': os.popen( "ruby -rrbconfig -e \"print RbConfig::CONFIG['RUBY_SO_NAME']\" " ).read()
            }
        else:
            self.ruby_config = {
                'arch': os.popen( "ruby -rrbconfig -e \"print Config::CONFIG['arch']\" " ).read(),
                'archdir': os.popen( "ruby -rrbconfig -e \"print Config::CONFIG['archdir']\" " ).read(),
                'hdrdir': os.popen( "ruby -rrbconfig -e \"print Config::CONFIG['rubyhdrdir']\" " ).read(),
                'libdir': os.popen( "ruby -rrbconfig -e \"print Config::CONFIG['libdir']\" " ).read(),
                'libruby': os.popen( "ruby -rrbconfig -e \"print Config::CONFIG['RUBY_SO_NAME']\" " ).read()
            }

        # Python configuration
        ldflags = os.popen( "python-config --ldflags" ).read().rstrip()
        includes = os.popen( "python-config --includes" ).read().rstrip()
        libdir = [flag.lstrip('-L') for flag in ldflags.split(' ') if flag.startswith('-L')]
        if self.ubuntu12 and len(libdir) != 1:
            raise RuntimeError, ("Could not find one -L option in python ldflags: %s" % ldflags)
        libpython = [flag.lstrip('-l') for flag in ldflags.split(' ') if flag.startswith('-lpy')]
        if len(libpython) != 1:
            raise RuntimeError, ("Could not find one library beginning -lpy in python ldflags: %s" % ldflags)

        self.python_config = {
            'includes': includes,
            'ldflags': ldflags,
            'libdir': libdir[0],
            'libpython': libpython[0]
        }

        # Java JDK configuration
        jni_headers = os.popen("find /usr/lib -type d ! -readable -prune -o -name jni.h -print").read().rstrip()
        jni_headers = jni_headers.split(" ")
        if len(jni_headers) == 0:
            raise RuntimeError, ("Java JDK could not be found under /usr/lib")

        jni_h = jni_headers[0]
        include = os.path.dirname(jni_h)
        java_home = os.path.dirname(include)

        if len(jni_headers) > 1:
            print("Multiple Java JDK jni.h headers found - using first of {}".format(jni_headers))

        self.java_config = {
            'include': include,
            'includes': "-I" + include,
            'java_home': java_home
        }

        # Check for validity of user options, configure things accordingly.

        self.timeoutBinary='/usr/bin/timeout'
        if not os.path.isfile(self.timeoutBinary):
            raise RuntimeError, "timeout executable not found in /usr/bin"

        if self.runs_per_test < 0:
            raise RuntimeError, "Cannot specify a negative number of test runs"

        # sort tags into positive and negative sets. Note that we
        # check for overlap later, since some options may implicitly
        # affect the set of tags (e.g. memcheck).
        self.test_tags_positive = set()
        self.test_tags_negative = set()
        for tag in self.test_tags_filter.split(","):
            if tag.startswith("-"):
                self.test_tags_negative.add(tag.strip('-'))
            elif tag.startswith("+"):
                self.test_tags_positive.add(tag.strip('+'))
            else:
                self.test_tags_positive.add(tag)

        self.test_concurrency_sema = None
        # If zero is specified, run two tests per cpu.
        if self.max_test_concurrency == 0:
            try:
                import multiprocessing
                self.max_test_concurrency = multiprocessing.cpu_count()
            except (ImportError,NotImplementedError):
                self.max_test_concurrency = int(os.sysconf('SC_NPROCESSORS_ONLN'))
            if self.max_test_concurrency > 0:
                self.max_test_concurrency *= 2

        if self.max_test_concurrency > 0:
            self.test_concurrency_sema = BoundedSemaphore(self.max_test_concurrency)


        self.error_color_prefix = str()
        self.ok_color_prefix = str()
        self.warning_color_prefix = str()
        self.reset_color_prefix = str()
        if self.test_report_color == True or (self.test_report_color == None and sys.stdout.isatty()):
            self.error_color_prefix='\033[1;31m'  # Red
            self.ok_color_prefix='\033[1;32m'  # Green
            self.warning_color_prefix='\033[1;33m'   # Amber
            self.reset_color_prefix='\033[1;m'     # Undo

        self.key_passed = 'PASSED'
        self.key_failed = 'FAILED'
        self.key_flakey = 'FLAKEY'

        # Configure toolchain.
        self.link = options['link']
        self.shlink = options['shlink']
        self.cc = options['cc']
        self.cxx = options['cxx']

        self.cppdefines = []
        self.cflags = []
        self.shcflags = []
        self.ccflags = []
        self.shccflags = []
        self.cxxflags = []
        self.shcxxflags = []
        self.linkflags = ['$__RPATH']
        self.shlinkflags = []
        self.cpppath = []

        self.boost_crypto_libs = []
        if self.ubuntu14:
            # The Boost in Trusty has been compiled with linkages to the crypto
            # and SSL libraries.  This causes some BB components to fail build
            # if they do not likewise include the linkages.  However, we don't
            # want to include them on platforms that don't need them.
            self.boost_crypto_libs = ['crypto', 'ssl']

        # Determine the installed verion of MongoDB.  This is somewhat of a
        # hack, but MongoDB does not advertise its version number in a way that
        # can be obtained from one of their header files, so it is necessary to
        # resort to this approach

        pion_ver = os.popen("pkg-config --modversion pion-net").read().rstrip()
        pion_ver_parts = re.split('\.', pion_ver)
        self.cppdefines += ["PION_VER_MAJOR=" + pion_ver_parts[0]]
        self.cppdefines += ["PION_VER_MINOR=" + pion_ver_parts[1]]
        self.cppdefines += ["PION_VER_PATCH=" + pion_ver_parts[2]]

        self.log4cpp_lib = []
        # Becauses of changes to the pion package for Trusty, it is necessary
        # on that platform for also link against log4cpp
        if self.ubuntu14:
            self.log4cpp_lib = [ 'log4cpp' ]

        self.add_nfs_symlinks = True
        self.test_ruby_swig = True
        if self.centos:
            # CentOS systems won't have the same /nfs mounts available
            self.add_nfs_symlinks = False
            # CentOS systems seem to have issues with the Swig Ruby tests
            self.test_ruby_swig = False

        def add_flags_if(flag, flags_name):
            if flag:
                self.cppdefines  += (options[flags_name].get('cppdefines') or [])
                self.cflags      += (options[flags_name].get('c') or [])
                self.shcflags    += (options[flags_name].get('shc') or [])
                self.ccflags     += (options[flags_name].get('cc') or [])
                self.shccflags   += (options[flags_name].get('shcc') or [])
                self.cxxflags    += (options[flags_name].get('cxx') or [])
                self.shcxxflags  += (options[flags_name].get('shcxx') or [])
                self.linkflags   += (options[flags_name].get('link') or [])
                self.shlinkflags += (options[flags_name].get('shlink') or [])

        add_flags_if(True, 'flags')
        add_flags_if(not self.ndebug, 'dbg_flags')
        add_flags_if(self.ndebug, 'ndbg_flags')
        add_flags_if(self.optimize, 'opt_flags')
        add_flags_if(not self.optimize, 'nopt_flags')
        add_flags_if(self.arcs, 'arc_flags')
        add_flags_if(self.coverage, 'cov_flags')
        add_flags_if(self.guess, 'guess_flags')
        add_flags_if(self.backtrace, 'backtrace_flags')
        add_flags_if(self.experimental, 'experimental_flags')
        add_flags_if(self.ubuntu14, 'ubuntu14_flags')
        add_flags_if(self.ubuntu12, 'ubuntu12_flags')
        add_flags_if(self.centos7, 'centos7_flags')
        add_flags_if(self.centos6, 'centos6_flags')
        add_flags_if(self.step_logging, 'step_logging_flags')
        add_flags_if(self.suppress_stdout, 'suppress_stdout_flags')

        if self.luajit:
            self.cppdefines += ['BB_USE_LUAJIT']
        if self.centos:
            self.lua_launcher = '/usr/bin/lua'
            self.luaincludepath = '/usr/include'
            self.cpppath += [self.luaincludepath]
        else:
            self.lua_launcher = self.luajit and '/usr/bin/luajit-2.0.0-beta5' or '/usr/bin/lua5.1'
            self.luaincludepath = self.luajit and '/usr/include/luajit-2.0' or '/usr/include/lua5.1'
            self.cpppath += [self.luaincludepath]

        # A facility to allow the user to tunnel additional flags to
        # the build from the command line. The format of the arguments
        # is like 'scons cflags="-q -blah" ...' for normal flags, and
        # 'scons cppdefines="XXX YYY" ...' to add -DXXX -DYYY to the
        # build line. In addition, for cppdefines, you may specify
        # values for the defines, like 'scons cppdefines="XXX YYYY=7"
        # ... '. If you don't like this style for cppdefines, you can
        # always just use 'scons cflags="-DFOO=bar" ...'. Finally, all
        # of these options may be repeated multiple times on the
        # command line; the values will be appended. Finally, notice
        # that these arguments are always appended to the list of
        # existing arguments, so they should override earlier
        # arguments on the command line in most cases.
        arg_keys = ("cppdefines", "cflags", "ccflags", "cxxflags", "linkflags", "shlinkflags")
        for key, values in arglist:
            if not key in arg_keys:
                raise RuntimeError, "Attempt to append to unknown flag class '%s'" % key
            value_list = values.split(' ')
            for value in value_list:
                getattr(self, key).append(value)

        # We want to inform gcc to never use builtins for a number of
        # memory allocation entry points since we want to be able to
        # swap out the allocator. Its not clear that gcc actually
        # _does_ use builtins, but just to be sure:
        if self.toolchain is 'gcc':
            for func in ("malloc", "free", "realloc", "calloc", "cfree", "memalign", "posix_memalign", "valloc", "pvalloc"):
                self.ccflags.append('-fno-builtin-' + func)

        # create the base environment
        self.baseEnv = Environment(
            CC=self.cc,
            CXX=self.cxx,
            CPPDEFINES=self.cppdefines,
            CPPPATH=self.cpppath,
            CFLAGS=self.cflags,
            SHCFLAGS=self.shcflags,
            CCFLAGS=self.ccflags,
            SHCCFLAGS=self.shccflags,
            CXXFLAGS=self.cxxflags,
            SHCXXFLAGS=self.shcxxflags,
            LINK=self.link,
            SHLINK=self.shlink,
            LINKFLAGS=self.linkflags,
            SHLINKFLAGS=self.shlinkflags,
            ENV=self.env,
            SWIGPATH=self.cpppath,
            TEST_RESULTS={}
        )

        if self.clang_analyze:
            if os.path.exists('.clang_analyze'):
                shutil.rmtree('.clang_analyze')
            if not os.path.exists('.clang_analyze'):
                os.mkdir('.clang_analyze')
            self.baseEnv['ENV']['CCC_CXX'] = self.baseEnv['CXX']
            self.baseEnv['ENV']['CCC_CC'] = self.baseEnv['CC']
            self.baseEnv['CC'] = '/usr/share/clang/scan-build/ccc-analyzer'
            self.baseEnv['CXX'] = '/usr/share/clang/scan-build/c++-analyzer'
            self.baseEnv['LINK'] = 'clang++'
            self.baseEnv['SHLINK'] = 'clang++'
            self.baseEnv['ENV']['CCC_ANALYZER_CPLUSPLUS'] = 1
            self.baseEnv['ENV']['CCC_ANALYZER_OUTPUT_FORMAT'] = 'html'
            self.baseEnv['ENV']['CCC_ANALYZER_HTML'] = '.clang_analyze'

        # GCC 4.5.2 doesn't give spurious strict aliasing warnings
        # anymore. For any earlier compilers, add in the flag to make
        # the warning not an error.
        if self.baseEnv['CC'].find('gcc') != -1:
            ccmajor,ccminor,ccpatch = [int(x) for x in self.baseEnv['CCVERSION'].split('.')]
            if (ccmajor < 4) or (ccmajor == 4 and ccminor < 5) or (ccmajor == 4 and ccminor == 5 and ccpatch < 2):
                self.baseEnv.AppendUnique(CCFLAGS = '-Wno-error=strict-aliasing')
                self.baseEnv.AppendUnique(CCFLAGS = '-fno-strict-aliasing')

        # this pads the RPATH so that chrpath has some room to grow
        # if this is just ORIGIN/../lib then when chrpath tries to make it ORIGIN/../../lib, it fails
        # this is a problem for standalone projects outside of bb (which use the bb build system)
        self.baseEnv.AppendUnique(RPATH=self.baseEnv.Literal(os.path.join("\\$$ORIGIN", os.pardir, "libFUTURERPATHPADDING_1234567890123456798901234567890")))

        # need to educate scons about this global alias
        # otherwise depending on it before it is created causes it to be local to the project
        self.baseEnv.Alias('all-binaries')

        # We are using the C++ compiler for linking so we want compiler flags on link line
        # so throw all of the relevant flags on.
        if "$CCFLAGS" not in self.baseEnv['LINKCOM']:
            self.baseEnv['LINKCOM'] = self.baseEnv['LINKCOM'].replace('$LINKFLAGS', '$CCFLAGS $LINKFLAGS')

        if "$CXXFLAGS" not in self.baseEnv['LINKCOM']:
            self.baseEnv['LINKCOM'] = self.baseEnv['LINKCOM'].replace('$LINKFLAGS', '$CXXFLAGS $LINKFLAGS')

        if "$SHCCFLAGS" not in self.baseEnv['SHLINKCOM']:
            self.baseEnv['SHLINKCOM'] = self.baseEnv['SHLINKCOM'].replace('$SHLINKFLAGS', '$SHCCFLAGS $SHLINKFLAGS')

        if "$SHCXXFLAGS" not in self.baseEnv['SHLINKCOM']:
            self.baseEnv['SHLINKCOM'] = self.baseEnv['SHLINKCOM'].replace('$SHLINKFLAGS', '$SHCXXFLAGS $SHLINKFLAGS')

        # Shared targets don't include the non-shared flags, but we want them too
        for com in ('SHCCCOM', 'SHCXXCOM', 'SHLINKCOM'):
            self.baseEnv[com] = self.baseEnv[com].replace('$SHCFLAGS', '$CFLAGS $SHCFLAGS')
            self.baseEnv[com] = self.baseEnv[com].replace('$SHCCFLAGS', '$CCFLAGS $SHCCFLAGS')
            self.baseEnv[com] = self.baseEnv[com].replace('$SHCXXFLAGS', '$CXXFLAGS $SHCXXFLAGS')
            self.baseEnv[com] = self.baseEnv[com].replace('$SHLINKFLAGS', '$LINKFLAGS $SHLINKFLAGS')

        # NOTE(acm): The SCons manpage discussion of 'MD5-timestamp'
        # convinces me that this is safe, and it takes a good chunk of
        # time (over a minute) off a request to rebuild when
        # everything is up to date than if we just use the standard
        # MD5 decider.
        self.baseEnv.Decider('MD5-timestamp')

        if not self.verbose_targets:
            self.baseEnv['CCCOMSTR'] = "Compiling [C]: $SOURCE"
            self.baseEnv['SHCCCOMSTR'] = "Compiling [C]: $SOURCE"
            self.baseEnv['CXXCOMSTR'] = "Compiling [C++]: $SOURCE"
            self.baseEnv['SHCXXCOMSTR'] = "Compiling [C++]: $SOURCE"
            self.baseEnv['LINKCOMSTR'] = "Linking: $TARGET"
            self.baseEnv['SHLINKCOMSTR'] = "Linking: $TARGET"
            self.baseEnv['SWIGCOMSTR'] = "SWIG'ing: $TARGET"
            self.baseEnv['DEBUGSTRIPSTR'] = "Creating Separate Debug File: $TARGET"
            self.baseEnv['CHRPATHSTR'] = "Setting install RPATH for $TARGET"
            self.baseEnv['SHDATAOBJCOMSTR'] = "Compiling [DATA]: $SOURCE"
            self.baseEnv['SHDATAOBJROCOMSTR'] = "Marking compiled data as read-only: $TARGET"

        # fix swig dependency tracking:
        # http://www.scons.org/wiki/SwigBuilder and
        # http://www.nabble.com/Problem-with-wiki-Swig-Scanner-t3586503.html
        SWIGScanner = SCons.Scanner.ClassicCPP(
            "SWIGScan",
            ".i",
            "SWIGPATH",
            '^[ \t]*[%,#][ \t]*(?:include|import|extern)[ \t]*(<|"?)([^>\s"]+)(?:>|"?)'
            )
        self.baseEnv.Prepend(SCANNERS=[SWIGScanner])

        # external library dependencies
        self.boost_libs = []
        self.boost_regex_lib = []
        self.boost_serialization_lib = []
        if self.centos:
            # On CentOS, the Boost libraries are still shipped in single
            # threaded and multi-threaded variants
            self.boost_libs = ['boost_date_time-mt', 'boost_system-mt', 'boost_filesystem-mt', 'boost_thread-mt', 'boost_program_options-mt', 'boost_regex-mt']
            self.boost_serialization_lib = ['boost_serialization-mt']
            self.boost_regex_lib = ['boost_regex-mt']
            self.boost_system_lib = ['boost_system-mt']
            self.boost_filesystem_lib = ['boost_filesystem-mt']
            self.boost_program_options_lib = ['boost_program_options-mt']
        else:
            # On Ubuntu, the Boost libraries are all multi-threaded and the
            # library names with the -mt suffix (which were just convenience
            # symlinks in Precise) were discontinued between Precise and Trusty
            self.boost_libs = ['boost_date_time', 'boost_system', 'boost_filesystem', 'boost_thread', 'boost_program_options', 'boost_regex']
            self.boost_serialization_lib = ['boost_serialization']
            self.boost_regex_lib = ['boost_regex']
            self.boost_system_lib = ['boost_system']
            self.boost_filesystem_lib = ['boost_filesystem']
            self.boost_program_options_lib = ['boost_program_options']

        self.misc_libs  = ['uuid', 'rt', 'numa']
        self.mysql_libs = ['mysqlclient', 'mysqlpp']
        self.test_libs  = ['cppunit', 'dl']
        self.intel_libs = ['ipp_z']
        self.intel_link_flags = []
        # When linking against the Intel IPP library on Trusty, the link fails:
        # //usr/lib/libiomp5.so: undefined reference to `pthread_atfork'
        #
        # Essentially, the linker cannot find the `pthread_atfork' symbol, which
        # is actually located in the static library libpthread_nonshared.a
        # instead of the shared phtread library.  The reason has to do with the
        # linker finding the symbol, but then purging the symbol because nothing
        # refers to it.  Only to later find that libiomp5.so refers to it, at
        # which time the reference cannot be resolved.  Please see this for more
        # detail:
        # http://ryanarn.blogspot.com/2011/07/curious-case-of-pthreadatfork-on.html
        #
        # In addition to the solution described (pass '-Wl,-u,pthread_atfork'
        # to the linker to force it to keep the symbol around), we also need to
        # pass '-Wl,--allow-shlib-undefined' to counteract the effect of
        # '-Wl,--no-undefined', which is set as a global linker option
        if self.ubuntu14:
            self.intel_link_flags = [ '-Wl,-u,pthread_atfork', '-Wl,--allow-shlib-undefined' ]

        if self.centos:
            # Ensure we do not link tcmalloc twice
            self.no_tcmalloc = not self.optimize
            self.no_tcmalloc_debug_features = self.optimize

        if self.centos:
            self.lua5_libs   = ['lua-5.1', 'luabind']
        else:
            self.lua5_libs   = ['lua5.1', 'luabind']
        self.luajit_libs = ['luajit-5.1', 'luabind-luajit']
        self.lua_libs = self.luajit and self.luajit_libs or self.lua5_libs

        if not self.no_tcmalloc:
            self.malloc_impl_lib = ['tcmalloc_minimal']
            if not self.optimize and not self.ndebug and not self.no_tcmalloc_debug_features:
                self.malloc_impl_lib = ['tcmalloc_debug']
            self.malloc_libs = self.malloc_impl_lib
        else:
            self.malloc_libs = []

        # core
        self.bbcore_libs = ['bbcore'] + self.boost_libs + self.lua_libs + self.misc_libs
        self.bbio_libs = ['bbio', 'bbthreading']
        self.bbio_pcap_libs = ['bbio_pcap'] + self.bbio_libs
        self.bbio_mq_libs = ['bbio_mq'] + self.bbio_libs

        # db
        self.db_include = ['/usr/include/mysql']
        self.bbdb_libs = ['bbdb'] + self.mysql_libs

       # simulator
        self.bbsimulator_libs = ['bbtrading', 'bbsimulator', 'tdcore', 'bbclientcore'] + self.bbdb_libs + self.lua_libs + self.bbcore_libs


        # pick the name to use for the build directory
        self.buildFlava = ""
        if self.ndebug:
            self.buildFlava += "ndebug_"
        if self.optimize:
            self.buildFlava += "optimize_"
        if self.arcs or self.guess:
            self.buildFlava += "arcs_"
        if self.coverage:
            self.buildFlava += "coverage_"
        if self.backtrace:
            self.buildFlava += "backtrace_"
        if self.experimental:
            self.buildFlava += "experimental_"
        if self.luajit:
            self.buildFlava += "lj2_"
        if self.toolchain != ACR_CompilerDefault:
            cleanComp = re.sub(r'[^a-zA-Z0-9-.]',  r'', self.toolchain)
            self.buildFlava += "comp_" + cleanComp + "_"
        if self.buildFlava == "":
            self.buildFlava = "default"
        # remove trailing _
        self.buildFlava = self.buildFlava.rstrip("_")

        # add release to the buildFlava (allows building different OS versions in same tree)
        self.buildFlava += "_%s" % self.distro
        self.buildFlavaDir = self.bb_build_root.Dir(self.buildFlava)

        # NOTE(acm): Setup CPPPATH. This is tricky, please try not to
        # modify. Basically, we want to hit the build directory, and
        # its thirdparty, but fall back on bb_root, and its
        # thirdparty, in that order.

        bb_include = self.bb_root.Dir('include')
        # lowest priority: bb_root's thirdparty directory
        self.baseEnv.PrependUnique(CPPPATH=[bb_include.Dir('bb').Dir('thirdparty')])
        # next lowest priority: bb_root's include directory
        self.baseEnv.PrependUnique(CPPPATH=[bb_include])
        # we prefer to get thirdparty from in-tree
        self.baseEnv.PrependUnique(CPPPATH=[self.buildFlavaDir.Dir('bb').Dir('thirdparty')])
        # Jadedragon includes end up in a separate 'jadedragon' subdir.
        # If we don't prepend this here, we're going to pick up the installed headers, which
        # might/probably will be old.
        self.baseEnv.PrependUnique(CPPPATH=[self.buildFlavaDir.Dir('jadedragon')])
        # And this is not consistent - headers that live in jadedragon/strategy/stratlib will be copied
        # over to /root/include/stratlib. To get around this, we look inside jadedragon/strategy already.
        self.baseEnv.PrependUnique(CPPPATH=[self.buildFlavaDir.Dir('jadedragon').Dir('strategy')])
        # and we prefer to get all other headers from in-tree
        self.baseEnv.PrependUnique(CPPPATH=[self.buildFlavaDir])

        # NOTE(acm): Setup LIBPATH. Same idea. We put the bb_root on
        # the LIBPATH here. So where is the bit that prefers to hit
        # the in-tree libs? See below in 'finalize' where we quite
        # purposely use PrependUnique to put in-tree lib paths first.
        self.baseEnv.PrependUnique(LIBPATH=[self.bb_root.Dir('lib')])

        # NOTE(acm): Setup SWIGPATH. There doesn't seem to be any
        # actual need to have /with/bb/root in the swigpath, but I suppose
        # it can't hurt. Again, we cons this up in reverse priority,
        # so /with/bb/root comes first.
        self.baseEnv.PrependUnique(SWIGPATH=[bb_include])
        self.baseEnv.PrependUnique(SWIGPATH=[self.buildFlavaDir])

        self.testReportCommand = self.baseEnv.Command(
            "testreport", [],
             self.baseEnv.Action(self.testReportBuild, self.testReportString))
        self.baseEnv.AlwaysBuild(self.testReportCommand)

        # remove the default 'Program' builder and replace it with a PseudoBuilder.
        del self.baseEnv['BUILDERS']['Program']
        del self.baseEnv['BUILDERS']['SharedLibrary']

        # use AddMethod to create a pseudo-builder called 'Program' that invokes
        # the method PseudoProgram when Program is called.
        self.baseEnv.AddMethod(self.PseudoProgram, "Program")
        self.baseEnv.AddMethod(self.PseudoSharedLibrary, "SharedLibrary")

        self.DebugFileAction = None
        if self.strip_style in ('debug', 'all'):
            command = ['eu-strip']
            # eu-strip with --strip-debug strips debug info but leaves symbols
            # eu-strip with no arguments strips both debug info and symbols
            if self.strip_style == 'debug':
                command += ['--strip-debug']
            command += ['$TARGET']
            # If the user wants the strip data preserved in a .debug
            # file, add the -f flag to eu-strip.
            if not self.strip_no_stripfile:
                command += ['-f']
                command += ['${TARGET}.debug']
            command = ' '.join(command)
            self.DebugFileAction = SCons.Action.Action( command, "$DEBUGSTRIPSTR" );

        # define the 'AcrProgram' builder which PseudoProgram will
        # invoke. This is basically identical to the normal definition
        # of 'Program'. PseudoProgram will invoke this after doing
        # whatever it is it wants to manipulate the arguments.
        self.baseEnv['BUILDERS']['AcrProgram'] = SCons.Builder.Builder(
            action = [
                       SCons.Defaults.LinkAction,
                       self.DebugFileAction
                     ],
            emitter = '$PROGEMITTER',
            prefix = '$PROGPREFIX',
            suffix = '$PROGSUFFIX',
            src_suffix = '$OBJSUFFIX',
            src_builder = 'Object',
            target_scanner = SCons.Scanner.Prog.ProgramScanner())

        self.baseEnv['BUILDERS']['AcrSharedLibrary'] = SCons.Builder.Builder(
            action = [
                       SCons.Defaults.SharedCheck,
                       SCons.Defaults.ShLinkAction,
                       self.DebugFileAction
                     ],
            emitter = '$SHLIBEMITTER',
            prefix = '$SHLIBPREFIX',
            suffix = '$SHLIBSUFFIX',
            src_suffix = '$SHOBJSUFFIX',
            src_builder = 'SharedObject',
            target_scanner = SCons.Scanner.Prog.ProgramScanner())

        # If you include a .lua file in your source list for a shared
        # library, it will get injected as data in your .so that you
        # can load.
        #
        # NOTE(acm): The 'cd'ing is annoying, but unavoidable, since
        # ld in '-b binary' mode uses the name of the input file to
        # set the symbol names, and if there is path info on the
        # filename that ends up as part of the symbol name, which is
        # no good. So we have to CD into the source directory so we
        # can use the unqualified name of the source file. We need to
        # abspath $TARGET since it might be a relative path, which
        # would be invalid after the CD.

        self.baseEnv['SHDATAOBJCOM'] = 'cd $$(dirname $SOURCE) && ld -s -r -o $TARGET.abspath -b binary $$(basename $SOURCE)'
        self.baseEnv['SHDATAOBJROCOM'] = 'objcopy --rename-section .data=.rodata,alloc,load,readonly,data,contents $TARGET $TARGET'

        self.baseEnv['BUILDERS']['AcrSharedLibrary'].add_src_builder(
            SCons.Script.Builder(
                action = [
                    SCons.Action.Action(
                        "$SHDATAOBJCOM",
                        "$SHDATAOBJCOMSTR"
                        ),
                    SCons.Action.Action(
                        "$SHDATAOBJROCOM",
                        "$SHDATAOBJROCOMSTR"
                        ),
                    ],
                suffix = '$SHOBJSUFFIX',
                src_suffix='.lua',
                emitter = SCons.Defaults.SharedObjectEmitter ) )

        # /with/bb/root is a symlink.  If the symlink points to something non-
        # existent, create a new directory where the symlink is pointing.
        def make_bb_root(target, source, env):
            t = target[0]
            if not os.path.exists(t.abspath):
                try:
                    os.mkdir(t.abspath)
                except OSError, err:
                    if err.errno == errno.EEXIST:
                        try:
                            p = os.readlink(t.abspath)
                        except:
                            raise err
                        os.mkdir(p)

        MakeBBRootBuilder = self.baseEnv.Builder(action=SCons.Action.Action(make_bb_root, lambda a,b,c: None),
            target_factory=self.baseEnv.Dir,
            target_scanner=SCons.Defaults.DirEntryScanner)
        self.baseEnv.Append(BUILDERS = {'MakeBBRootDir':MakeBBRootBuilder})
        self.baseEnv.MakeBBRootDir(self.bb_root, [])

        # Coverage and ICECC don't work together
        if self.coverage and self.icecc:
            raise RuntimeError, "--icecc does not work correctly for --coverage builds"

        # Protect against people saying 'valgrind' when they mean 'memcheck'.
        if self.run_tests_under == "valgrind":
            raise RuntimeError, "If you want to run tests under valgrind, either say 'run-tests-under=memcheck', or pass an absolute tool path to run-tests-under and provide appropriate run-under-args"

        # special case handling for run_tests_under={memcheck|callgrind}
        if self.run_tests_under in ["memcheck", "callgrind"]:
            grindutils_dir = self.baseEnv.Dir("#").Dir('etc/valgrind/').abspath
            if not os.path.exists( grindutils_dir ):
                grindutils_dir = self.baseEnv.Dir("#").Dir('bb/etc/valgrind/').abspath
            if not os.path.exists( grindutils_dir ):
                raise "Unable to locate the valgrind utils directory. It should be in either {build_root}/etc/valgrind or in {build_root}/bb/etc/valgrind"

            if self.run_tests_under == "memcheck":
                self.run_tests_under = grindutils_dir + "/memcheck.acr"
                self.run_under_args += ["--read-var-info=yes"]
                self.run_under_args += ["--error-exitcode=1"]
                self.run_under_args += ["--leak-check=full"]
                self.run_under_args += ["--track-fds=yes"]

                # NOTE(acm): This sucks, but see:
                #
                # http://bugs.kde.org/show_bug.cgi?id=167483
                # http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=456303.
                #
                # There doesn't seem to be much else we can do about
                # it, and we really do want to set an RPATH so we can
                # use $ORIGIN.
                self.run_under_args += ["--run-libc-freeres=no"]

                # Make sure that tests tagged 'novalgrind' are in the
                # negative test tags (and not in the positive tags).
                self.test_tags_positive.discard('novalgrind')
                self.test_tags_positive.discard('novalgrind-%s' % self.distro)
                self.test_tags_negative.add('novalgrind')
                self.test_tags_negative.add('novalgrind-%s' % self.distro)

            elif self.run_tests_under == "callgrind":
                self.run_tests_under = grindutils_dir + "/callgrind.acr"

            # if we are using the default timeout scaling, up it
            # considerably due to VEX overhead.
            if self.test_timeout_scale_factor == 1:
                self.test_timeout_scale_factor = 20

        # if building in debug mode then add the negative tag "nodebug"
        if not self.optimize:
            self.test_tags_negative.add('nodebug')

        # check that our sets of tags are disjoint
        if not len(self.test_tags_positive.intersection(self.test_tags_negative)) == 0:
            raise RuntimeError, "A tag cannot be both positive and negative"

        # some state for our final build summary
        self.testsWereRun = False
        self.finalTestResults = None
        atexit.register(self.BuildSummary)

    def BuildSummary(self):
        from SCons.Script import GetBuildFailures

        # print the test report if there is one
        if self.finalTestResults:
            reports = defaultdict(dict)
            totals = defaultdict(int)

            print_passed_logfiles = (self.dump_test_logs == "all")
            print_failed_logfiles = (self.dump_test_logs == "all" or self.dump_test_logs == "failed")

            test_keys = self.finalTestResults.keys()
            if len(test_keys) != 0:
                test_keys.sort()

                filters = (
                    (self.key_passed, lambda passed, failed: failed == 0,                 self.ok_color_prefix,      print_passed_logfiles),
                    (self.key_flakey, lambda passed, failed: passed != 0 and failed != 0, self.warning_color_prefix, print_failed_logfiles),
                    (self.key_failed, lambda passed, failed: passed == 0,                 self.error_color_prefix,   print_failed_logfiles),
                    )

                for filter in filters:
                    for test in test_keys:
                        outcomes = self.finalTestResults[test]
                        passed_outcomes = outcomes[self.key_passed]
                        failed_outcomes = outcomes[self.key_failed]
                        passed = len(passed_outcomes)
                        failed = len(failed_outcomes)

                        disposition = filter[0]
                        display_predicate = filter[1]
                        color = filter[2]
                        show_logs = filter[3]

                        if display_predicate(passed, failed):

                            totals[disposition] += 1

                            deltas = []

                            # sum up the test runtimes and then get the average
                            delta_sum = datetime.timedelta(0, 0, 0)
                            for p in passed_outcomes:
                                deltas.append(passed_outcomes[p][2])
                                delta_sum += passed_outcomes[p][2]
                            for p in failed_outcomes:
                                deltas.append(failed_outcomes[p][2])
                                delta_sum += failed_outcomes[p][2]

                            delta_avg = delta_sum / len(deltas)
                            runtime_string = "[%sruntime: %s]" % ("avg " if self.runs_per_test > 1 else "", delta_avg)

                            # for more than one run per test, computer the standard deviation
                            std_div_string = ""
                            if self.runs_per_test > 1:
                                d2_sum = 0

                                for d in deltas:
                                    diff = d - delta_avg
                                    diff_sec = diff.days * 86400 + diff.seconds + diff.microseconds/10.0**6
                                    d2_sum += (diff_sec * diff_sec)

                                d2_sum = d2_sum / len(deltas)
                                std_div = math.sqrt(d2_sum)
                                std_div_string = "[std deviation: %0.5f]" % std_div

                            message = "%s[%s (%04dP, %04dF)]%s%s %s%s" % (color,
                                                                      disposition,
                                                                      passed,
                                                                      failed,
                                                                      runtime_string,
                                                                      std_div_string,
                                                                      test,
                                                                      self.reset_color_prefix)

                            if not show_logs and disposition == self.key_flakey:
                                failed_iterations = outcomes[self.key_failed].keys();
                                failed_iterations.sort()
                                message += "\t{ failed: %s }" % (failed_iterations)

                            print message

                            if show_logs:
                                for i in xrange(0, self.runs_per_test):
                                    itername = i + 1
                                    logfile = None
                                    if itername in outcomes[self.key_passed]:
                                        disposition = self.key_passed
                                        color = self.ok_color_prefix
                                    elif itername in outcomes[self.key_failed]:
                                        disposition = self.key_failed
                                        color = self.error_color_prefix

                                    logfile = outcomes[disposition][itername][1]
                                    print '---------------- %s%s%s: %s ---------------' % (color,
                                                                                           disposition,
                                                                                           self.reset_color_prefix,
                                                                                           logfile)
                                    if disposition == self.key_failed:
                                        with open(logfile, 'r') as f:
                                            for line in f:
                                                print "\t" + line,
                                            print '\n'

                            elif disposition == self.key_flakey:
                                failed_iterations = outcomes[self.key_failed].keys();
                                failed_iterations.sort()

                if totals[self.key_failed] == 0 and totals[self.key_flakey] == 0:
                    print self.ok_color_prefix + "ALL TESTS PASSED" + self.reset_color_prefix
                else:
                    color_prefix = self.error_color_prefix
                    if totals[self.key_failed] == 0:
                        color_prefix = self.warning_color_prefix
                    print "%sTESTS FAILED: %d %s, %d %s%s" % (color_prefix,
                                                              totals[self.key_failed],
                                                              self.key_failed,
                                                              totals[self.key_flakey],
                                                              self.key_flakey,
                                                              self.reset_color_prefix)
                    if self.failed_tests_dont_fail_build:
                        print "\n%sIGNORING TEST FAILURES AT USERS REQUEST%s" % (self.warning_color_prefix,
                                                                                 self.reset_color_prefix);
        elif self.testsWereRun:
            print "%sWARNING: Tests were run, but no report generated: a test probably failed to build%s" % (self.warning_color_prefix, self.reset_color_prefix)

        # print any build failures that aren't the test report
        failures = GetBuildFailures()
        if failures:
            for bf in GetBuildFailures():
                nodeStr = str(bf.node)
                errStr = bf.errstr
                if nodeStr != 'testreport':
                    print "%sTARGET FAILED: %s%s" % (self.error_color_prefix, nodeStr, self.reset_color_prefix)
            print "%sBUILD FAILED%s" % (self.error_color_prefix, self.reset_color_prefix)
        else:
            print "%sBUILD OK%s" % (self.ok_color_prefix, self.reset_color_prefix)

    def addDebugFileToEmitter(self, env, emitterName):

        # A guard to prevent us from repeatedly adding the
        # debugemitter if we have already done so for this emitter
        # name.
        emitterAttrName = 'acrdebugemitter_%s' % emitterName
        if not hasattr(env, emitterAttrName):
            setattr(env, emitterAttrName, True)

            try:
                origEmitters = env[emitterName]
                if type(origEmitters) != list:
                    origEmitters = [origEmitters]
            except KeyError:
                origEmitters = []

            def emitter(target, source, env):
                for origEmitter in origEmitters:
                    target, source = origEmitter(target, source, env)

                if not self.strip_no_stripfile:
                    debugfile = env.arg2nodes(str(target[0]) + '.debug', target = target[0], source = source[0])[0]
                    target[0].attributes.debugfile = debugfile
                    debugfile.attributes.isdebugfile = True
                    target.append(debugfile)
                return target, source

            env[emitterName] = emitter

    # run after processing all scons files
    # go through the list of targets
    # and add rpath and libpath if needed
    # this should be called at the end of all other sconscript file processing when all targets are known
    # the reason this can't happen at build time is because scons doesn't like it when the flags change
    # behind it's back. By running this before any building happens, scons can know what the flags are
    def finalize(self):
        for t in self.targets:
            for node in t:
                paths = []

                # for every library this node wants to use
                # see if it is a locally built one, if it is, set the rpath to the local path
                # the rpath is changed at install time to be relative to origin
                for l in node.env['LIBS']:
                    if self.local_libs.has_key(l):
                        tgt = self.local_libs[l]
                        path = os.path.dirname(tgt[0].get_abspath())
                        paths.append(path)

                # NOTE(acm): It is very important that LIBPATH be a
                # prepend here, so that it interposes before our
                # standard LIBPATH which points into /with/bb/root.
                if len(paths) > 0:
                    node.env.PrependUnique(RPATH=paths)
                    node.env.PrependUnique(LIBPATH=paths)

        if self.enable_build_stamps:

            def WriteBuildStamp( target, source, env ):
                ostr = open(str(target[0]), 'w')
                ostr.write( "bb_root = '%s'\n" % (self.bb_root))
                ostr.write( "working_dir = '%s'\n" % (os.getcwd()))
                ostr.write( "build_time = '%s'\n" % (time.asctime()))
                ostr.write( "hostname = '%s'\n" % (socket.getfqdn()))
                ostr.write( "username = '%s'\n" % (os.getenv('LOGNAME')))
                ostr.write( "argv = %s\n" % (sys.argv))
                ostr.write( "uuid = %s\n" % uuid.uuid4())

            buildstamp = self.baseEnv.Command(
                [self.buildFlavaDir.File('buildstamp')], [], WriteBuildStamp)
            self.baseEnv.AlwaysBuild(buildstamp)
            buildstamp_install = self.AddEtc(buildstamp, makeInstall=True)

    def PseudoProgram(self, env, *args, **kwargs):
        # Append the malloc libraries to the user or env specified libs.
        kwargs['LIBS'] = (kwargs.get('LIBS') or env.get('LIBS') or []) + self.intel_libs + self.malloc_libs
        kwargs['LINKFLAGS'] = (kwargs.get('LINKFLAGS') or env.get('LINKFLAGS') or []) + self.intel_link_flags
        if self.strip_style in ('debug', 'all'):
            self.addDebugFileToEmitter(env, 'PROGEMITTER')
        target = env.AcrProgram(*args, **kwargs)
        target[0].attributes.rpath = kwargs.get('INSTALL_RPATH') if 'INSTALL_RPATH' in kwargs else None

        self.Alias('all-binaries', target)
        self.targets.append(target)
        return target

    def PseudoSharedLibrary(self, env, *args, **kwargs):
        if self.strip_style in ('debug', 'all'):
            self.addDebugFileToEmitter(env, 'SHLIBEMITTER')
        target = env.AcrSharedLibrary(*args, **kwargs)
        target[0].attributes.rpath = kwargs.get('INSTALL_RPATH') if 'INSTALL_RPATH' in kwargs else None

        libname = kwargs.get('target')
        if not self.local_libs.has_key(libname):
            self.local_libs[libname] = target

        self.Alias('all-binaries', target)
        self.targets.append(target)
        return target

    def Alias(self, name, node):
        self.baseEnv.Alias(name, node)

    def Default(self, node):
        self.baseEnv.Default(node)
        self.Alias('default', node)

    def MakeEnv(self, **args):
        env = self.baseEnv.Clone()
        env.AppendUnique(**args) # do any customization the caller asked for
        protoc.generate(env)
        return env

    def SharedLibVersion(self, basename, dir = "."):
        return SharedLibVersion(basename, self, dir)


    # Testing stuff: this is used as an action function in AddYesNoTest, see that for details
    def yesNoTestString(self, target, source, env):
        if(self.verbose_targets):
            return " ".join(self.generateYesNoTestCommand(target, source, env))
        return "Testing [%d of %d]: %s" % (env['ITERATION'], self.runs_per_test, env['TESTNAME'])


    def generateYesNoTestCommand(self, target, source, env):

        timeout= env['TIMEOUT']
        runner= env['RUNNER']
        # Make all paths absolute so things don't break when we change
        # our cwd to the rundir. Ideally, we could do this as relative
        # paths, but SCons on Hardy doesn't support rela_path.
        abs_sources = map(lambda x: self.baseEnv.File(x).abspath, source)
        abs_targets = map(lambda x: self.baseEnv.File(x).abspath, target)

        args = []
        if self.timeoutBinary:
            args.append(self.timeoutBinary)                  # Times out tests if they don't complete in a timely fashion
            # the timeout version on maverick accepts parameters differently from the lucid one
            if self.distro == "lucid":
                args.append("-%d" % self.test_timeout_signal)    #   Kill with selected signal
            else:
                args.append("--signal=%d" % self.test_timeout_signal)    #   Kill with selected signal
            args.append("%ss" % timeout)                     #   The specified timeout.
        if self.run_tests_under:                         # Do we have an instrumentation binary?
            args.append(self.run_tests_under)            #  Then prepend the instrumentation binary
            args.extend(self.run_under_args)             #  And add the arguments to that instrumentation
        if runner:                                       # Was a runner specified?
            args.append(runner)                          #   Then add the runner
        args.append(abs_sources[0])                      # The actual binary that is the test
        args.extend(env['TESTARGS'])                     #  And non-file arguments to it
        args.extend(abs_sources[1:])                     #  Followed by input files (skip 0, it is the binary)
        args.extend(abs_targets[1:])                     #  And output files        (skip 0, it is the runlog)

        return args


    def yesNoTestBuild(self, target, source, env):

        self.testsWereRun = True

        testName = env['TESTNAME']
        iteration = env['ITERATION']
        rundir = env['RUNDIR']

        if not testName in env['TEST_RESULTS']:
            env['TEST_RESULTS'][testName] = defaultdict(dict)

        # Inject 'BB_TEST_RUNDIR' into the OS environment that we will
        # pass to this test.
        env['ENV']['BB_TEST_RUNDIR'] = rundir.abspath

        # Set the timezone to US, otherwise the time tests fail
        env['ENV']['TZ']='EST5EDT,M3.2.0,M11.1.0'

        # need to inform ruby and lua tests where they can find their binding libraries
        baseDir = self.buildFlavaDir.Dir('bb').abspath
        env['ENV']['LUA_PATH'] = ';'.join([
                '/with/bb/conf/td/?.lua',
                '/with/bb/conf/qd/?.lua',
                '/with/bb/conf/core/?.lua',
                '%s/signals/?.lua' % baseDir,
                '%s/clientcore/?.lua' % baseDir,
                '%s/conf/?.lua' % baseDir,
                '%s/core/?.lua' % baseDir,
                env['ENV']['LUA_PATH']])
        env['ENV']['LUA_CPATH'] = '%s/utils/?.so;' % baseDir + env['ENV']['LUA_CPATH']
        env['ENV']['BB_DFS_ROOT'] = '/nfs/datafiles'
        env['ENV']['BB_TRADELOGS_ROOT'] = '/nfs/datafiles.tradelogs'
        env['ENV']['RUBYLIB'] = '%s/swig/ruby:' % baseDir + env['ENV']['RUBYLIB']

        # Build up our command line
        args = self.generateYesNoTestCommand(target,source, env)

        delta = datetime.timedelta(0, 0, 0)
        try:
            if self.test_concurrency_sema:
                self.test_concurrency_sema.acquire()

            # run the command
            start = datetime.datetime.now()
            popen = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env['ENV'], cwd=rundir.path)
            (commandOutput,ignore) = popen.communicate()
            end = datetime.datetime.now()
            delta = end - start
        finally:
            if self.test_concurrency_sema:
                self.test_concurrency_sema.release()

        # save the log
        with open(target[0].path, 'w') as f:
            f.write(commandOutput)
            f.write('\n')
            f.write("test runtime: %s\n" % delta)

        collection_key = self.key_passed
        if popen.returncode != 0:
            collection_key = self.key_failed

        env['TEST_RESULTS'][testName][collection_key][iteration] = (popen.returncode, target[0].path, delta)

        # report success to scons, because we don't want to stop running other tests. we will report failure
        # once all the tests have been run
        return 0

    # testReportBuild, testReportString are used to print a report once
    # all the tests are done running.
    def testReportString(self, target, source, env):
        self.finalTestResults = env['TEST_RESULTS']
        return None

    def testReportBuild(self, target, source, env):
        failed_tests = 0
        for test in env['TEST_RESULTS'].iterkeys():
            outcomes = env['TEST_RESULTS'][test]
            failed_tests += len(outcomes[self.key_failed])

        if not self.failed_tests_dont_fail_build and failed_tests > 0:
            return 1

        return 0

    def AddYesNoTests(self, tests, tags = []):
        for i in tests:
            self.AddYesNoTest(i, tags = tags)

        # A YesNo test is a runnable exe -- if it exits with 0 status, it passed, nonzero = failed
        # If args is nonempty, those arguments will be passed
        # If argFiles is nonempty, they should paths to files that scons knows about;
        # they will be passed as arguments to the tests (after args)
        # If outFiles is nonempty, they should paths to test output files;
        # they will be passed as arguments to the tests (after args)
    def AddYesNoTest(self, test, argFiles=[], args=[], installDeps=['conf'], outFiles=[], tags = [], tgtName = None):

        # Normalize tgtName if not overridden.
        tgtName = tgtName or test

        # every test must have the tag 'all'
        if not 'all' in tags:
            tags = tags + ['all']

        # Get the relative path to the test (against the build
        # directory), then strip the build prefix to get a nice
        # looking test name.
        testName = self.baseEnv.File(tgtName).tpath
        testNamePretty = testName[testName.find(self.buildFlava) + len(self.buildFlava) + 1:]

        inPositiveTags = False
        inNegativeTags = False
        for tag in tags:
            if tag in self.test_tags_positive: inPositiveTags = True
            if tag in self.test_tags_negative: inNegativeTags = True

        # by default, tests are 'small', meaning they get 90 seconds
        # to execute. You can tag your tests with 'longrun' or
        # 'longlongrun' to get higher timeouts.
        timeout = 90
        if 'longrun' in tags:
            timeout = 240
        elif 'longlongrun' in tags:
            timeout = 600
        timeout *= self.test_timeout_scale_factor

        # If you want the test to run by a particular launcher,
        # You can do this by specifying a tag runby.XXX where XXX is a special runner tag
        # Right now, only Lua is supported
        runner = None
        for tag in tags:
            if tag == "runby.lua": runner = self.lua_launcher

        aggregateCmd = []
        if (not 'performance' in tags) or ('performance' in tags and self.run_performance_tests):
            if inPositiveTags and not inNegativeTags:
                for i in xrange(0, self.runs_per_test):

                    iRunDir = self.baseEnv.Dir(tgtName + '.rundirs').Dir(i + 1)
                    iTgtName = iRunDir.File('runlog')
                    iOutFiles = map(lambda x: iRunDir.File(x), outFiles)

                    cmd = self.baseEnv.Command([iTgtName]+iOutFiles,
                                               [test]+argFiles,
                                               self.baseEnv.Action(self.yesNoTestBuild, self.yesNoTestString),
                                               ENV=os.environ,
                                               TESTARGS=args,
                                               ITERATION=(i + 1),
                                               RUNDIR=iRunDir,
                                               TESTNAME=testNamePretty,
                                               TIMEOUT=timeout,
                                               RUNNER=runner)
                    self.baseEnv.AlwaysBuild(cmd)

                    for i in installDeps:
                        self.baseEnv.Depends(cmd, self.GetInstallAlias(i))

                    aggregateCmd.append(cmd)

            testBaseName = os.path.basename(testNamePretty)

            self.BuildTests(test, aliases = ['tests', testBaseName])

            runTestsAliasName = 'run-tests'
            runTestAliasName = 'run-' + testBaseName
            runTestAlias = self.Alias(runTestAliasName, aggregateCmd)
            runTestsAlias = self.Alias(runTestsAliasName, runTestAliasName)

            if not self.no_defer_test_execution:
                for name in ['.', runTestsAliasName]:
                    if name in SCons.Script.BUILD_TARGETS:
                        self.baseEnv.Depends(aggregateCmd, 'all-binaries')
                        break

                for runAliasName in [runTestAliasName, runTestsAliasName]:
                    if runAliasName in SCons.Script.BUILD_TARGETS or '.' in SCons.Script.BUILD_TARGETS:
                        self.baseEnv.Depends(self.testReportCommand, aggregateCmd)
                        self.baseEnv.Depends(runAliasName, self.testReportCommand)

        return aggregateCmd

    def BuildTests(self, nodes, aliases = ['tests']):
        for i in aliases:
            self.Alias('build-'+i, nodes)

    def GetInstallAlias(self, libName):
        return self.baseEnv.Alias('install-'+libName)

    def AddSymlink(self, srcpath, destname, destdir='', makeInstall=True):
        dest = self.install.path
        if destdir != '':
            dest = os.path.join( dest, destdir )
        dest = os.path.join( dest, destname )

        if self.baseEnv.GetOption('clean') and os.path.exists(dest):
            os.remove(dest)

        # in case the destination exists but is not a link, leave it alone
        if os.path.exists(dest) and os.path.islink(dest) and os.path.dirname(os.readlink(dest)) != os.path.dirname(srcpath):
            try:
                os.remove(dest)
            except:
                pass

        tgt = self.baseEnv.Command(dest, srcpath, self.baseEnv.Action(
            SymlinkHelpers.build_it, SymlinkHelpers.string_it))
        if makeInstall:
            self.Alias('install', tgt)
        return tgt

    def AddLibSymlink(self, basenames):
        for basename in basenames:
            tgt = self.SharedLibVersion(basename).MakeSharedLibrarySymlink(self.baseEnv, self.lib)
            tgt = self.SharedLibVersion(basename).MakeBaseSharedLibrarySymlink(self.baseEnv, self.lib)
        return tgt

    def MakeChrpathAction(self, rpath):
        # Normalize to a list
        if type(rpath) != type([]):
            rpath = [rpath]

        rpath_literal_strs = []
        for rpath_component in rpath:
            rpath_literal_strs += [str(rpath_component)]
        rpath = self.baseEnv.Literal(':'.join(rpath_literal_strs))

        command = "chrpath -r %s $TARGET > /dev/null 2>&1" % rpath
        return SCons.Action.Action( command, "$CHRPATHSTR" )

    # Creates and returns an install target which installs 'source' into 'installdir'.
    # 'source' is usually a file copy.
    def Install(self, dir, source):

        if type(source) == type(str()):
            return self.baseEnv.Install(dir = dir, source = source)

        result = []
        for item in SCons.Util.flatten(source):

            if hasattr(item, 'attributes'):

                # If this target is a debug file, skip it: it will be installed
                # when its 'owning' target is processed
                if hasattr(item.attributes, 'isdebugfile'):
                    continue

                # This thing isn't a debugfile, so it should get installed now
                itemInstall = self.baseEnv.Install(dir = dir, source = item)
                result.append(itemInstall)

                if hasattr(item.attributes, 'rpath'):
                    rpath = item.attributes.rpath
                    if not rpath:
                        rpath = self.baseEnv.Literal(os.path.join("\\$$ORIGIN", os.pardir, "lib"))
                    for i in itemInstall:
                        self.baseEnv.AddPostAction(i, self.MakeChrpathAction(rpath))

                # If this thing owns a debugfile, then we process that
                # here and establish the proper dependency.
                if hasattr(item.attributes, 'debugfile'):
                    debugInstall = self.baseEnv.Install(dir = dir.Dir('.debug'), source = item.attributes.debugfile)
                    self.baseEnv.Depends( itemInstall, debugInstall )
                    result.append(debugInstall)

            else:
                result.append(self.baseEnv.Install(dir = dir, source = item))

        return result

    # Creates and returns an install target that copies 'files' into 'destdir'.
    # Explicitly creates destination directories
    # If makeInstall is True, adds the target to the 'install' target.
    def AddInstall(self, dir, source, makeInstall=True):
        installdir = dir
        tgt = self.Install(dir = installdir, source = source)
        if self.copyright_holder and not self.copyright_holder.isspace():
            self.baseEnv.AddPostAction(tgt, "sed -i 's/Shanghai ShanCe Technologies Company Ltd/" + self.copyright_holder + "/' $TARGET")
        if makeInstall:
            self.Alias('install', tgt)

        if self.enable_build_stamps:

            # Lazily construct the buildsigs target if not already done.
            if not hasattr(self, 'buildSigsTarget'):

                def WriteBuildSignatures( target, source, env ):
                    ostr = open(str(target[0]), 'w')
                    bb_scripts_root = os.environ.get('BB_SCRIPTS_ROOT')
                    command = '%s/build_tools/gen-bb-sigs %s' % (bb_scripts_root, self.bb_root)
                    ostr.write( os.popen(command).read() )
                    ostr.close()

                self.buildSigsTarget = self.baseEnv.Command(
                    [self.buildFlavaDir.File('buildsigs')], [], WriteBuildSignatures)
                self.baseEnv.AlwaysBuild(self.buildSigsTarget)
                install_buildSigs = self.AddEtc(self.buildSigsTarget, makeInstall=True)

            # The build sigs depend on any target that gets installed,
            # with an obvious exception for the build sigs themselves.
            if not source == self.buildSigsTarget:
                self.baseEnv.Depends( self.buildSigsTarget, tgt )

        return tgt

    def AddEtc(self, files, **args):
        return self.AddInstall(dir = self.etc, source = files, **args)

    def AddLib(self, files, **args):
        return self.AddInstall(dir = self.lib, source = files, **args)

    def AddRubyLib(self, files, **args):
        return self.AddInstall(dir = self.lib.Dir('ruby'), source = files, **args)

    def AddLuaLib(self, files, **args):
        return self.AddInstall(dir = self.lib.Dir('lua'), source = files, **args)

    def AddPythonLib(self, files, **args):
        return self.AddInstall(dir = self.lib.Dir('python'), source = files, **args)

    def AddJavaLib(self, files, **args):
        return self.AddInstall(dir = self.lib.Dir('java'), source = files, **args)

    def AddBin(self, files, **args):
        return self.AddInstall(dir = self.bin, source = files, **args)

    def AddTestBin(self, files, **args):
        return self.AddInstall(dir = self.testBin, source = files, **args)

    def AddConf(self, files, **args):
        return self.AddInstall(dir = self.conf, source = files, **args)

    def AddConfDir(self, directory, files, **args):
        newdir = self.install.Dir('conf/%s' % directory )
        return self.AddInstall(dir = newdir, source = files, **args)

    def AddInclude(self, files, base = 'bb', **args):
        return self.AddInstall(dir = self.include.Dir(base), source = files, **args)

    def AddExtInclude(self, ext, files, base = 'bb', **args):
        installdir = self.include.Dir(base).Dir(ext)
        return self.AddInstall(dir = installdir, source = files, **args)

    def AddService(self, servicename, files, **args):
        service_dir = self.service.Dir(servicename)
        return self.AddInstall(dir = service_dir, source = files, **args)

    # builds documentation with doxygen
    # puts it in /with/bb/root
    # returns the environment used
    def AddDocs(self, targetname, destdirname, doxyfilename, dependencylist = None):

        destdir = self.bb_root
        docsdir = destdir.Dir('docs').Dir(destdirname)
        docenv = SConsEnvironment()

        headers = [h for h in docenv.Glob('*.h')  if h.path.find('autogen') == -1]
        sources = [s for s in docenv.Glob('*.cc') if s.path.find('autogen') == -1]

        tgt = docenv.Command( docsdir.File('.tag'), [doxyfilename] + headers + sources,
                "cd ${SOURCE.dir} && doxygen")
        docenv.Clean( tgt, [docsdir, docsdir.File('.tag')] )
        docenv.AlwaysBuild( tgt )

        docenv.Depends( tgt, self.buildFlavaDir.File("bb/etc/doxygen/header.html" ) )
        docenv.Depends( tgt, self.buildFlavaDir.File("bb/etc/doxygen/footer.html" ) )

        if dependencylist:
            for dep in dependencylist:
                docenv.Depends( tgt, destdir.Dir('docs').Dir(dep).File('.tag') )
        self.Alias('doxygen', tgt)
        return docenv

    def EnableTreeStamps(self, treename):

        if self.enable_build_stamps:

            def WriteTreeStamp( target, source, env ):
                root = target[0].Dir('.').srcnode()
                ostr = open(str(target[0]), 'w')
                command = '/with/bb/scripts/build_tools/gen-tree-stamp %s' % (root)
                ostr.write( os.popen( command ).read() )
                ostr.close()

            def WriteTreeSigs( target, source, env ):
                root = target[0].Dir('.').srcnode()
                ostr = open(str(target[0]), 'w')
                command = '/with/bb/scripts/build_tools/gen-tree-sigs %s' % (root)
                ostr.write( os.popen( command ).read() )
                ostr.close()

            treestamp = self.baseEnv.Command('treestamp.' + treename, [], WriteTreeStamp)
            self.baseEnv.AlwaysBuild(treestamp)
            treestamp_install = self.AddEtc(treestamp, makeInstall=True)

            treesigs = self.baseEnv.Command('treesigs.' + treename, [], WriteTreeSigs)
            self.baseEnv.AlwaysBuild(treesigs)
            treesigs_install = self.AddEtc(treesigs, makeInstall=True)

            return [treestamp_install, treesigs_install]


def DumpEnv( env, key = None, header = None, footer = None ):
    """
    Using the standard Python pretty printer, dump the contents of the
    scons build environment to stdout.

    If the key passed in is anything other than 'env', then that will
    be used as an index into the build environment dictionary and
    whatever is found there will be fed into the pretty printer. Note
    that this key is case sensitive.

    The header and footer are simple mechanisms to allow printing a
    prefix and suffix to the contents that are dumped out. They are
    handy when using DumpEnv to dump multiple portions of the
    environment.
    """
    import pprint
    pp = pprint.PrettyPrinter( indent = 2 )
    if key:
        dict = env.Dictionary( key )
    else:
        dict = env.Dictionary()
    if header:
        print header
    pp.pprint( dict )
    if footer:
        print footer

# adds the method Dump to SconsEnvironment
from SCons.Script.SConscript import SConsEnvironment
SConsEnvironment.Dump = DumpEnv


# Represents a Shared Library in the ACR Build System
# Current shared library version numbers are stored in "basename.version" files,
# with the format YYYYMMDD.V  where YYYYMMDD is the RC name and V is the subrelease number.
class SharedLibVersion:

    # Creates a SharedLibVersion object for the library named 'basename'
    # with version information strored in directory 'dir'.
    def __init__(self, basename, acr, dir = "."):
        self.basename = basename
        self.dir = acr.baseEnv.Dir(dir).srcnode().abspath + "/"

    # returns the full pathname of the .version file for this library
    def GetVersionPathname(self):
        return self.dir + self.basename + ".version"

    # returns version of library
    def GetCurrentVersion(self):
        build_v = os.popen( "cat " + self.GetVersionPathname() ).read();
        if not build_v:
            raise RuntimeError, "no version file found for " + self.basename + ": " + self.GetVersionPathname()
        return build_v

    # returns version of library
    def GetCurrentVersionBase(self):
        build_v = self.GetCurrentVersion()
        return build_v[0:build_v.find('.')]

    # returns the name of a shared library with the current version number
    def GetSharedLibraryName(self):
        return "lib" + self.basename + ".so." + self.GetCurrentVersion()

    # returns the name of a shared library with a base version number
    def GetBaseSharedLibraryName(self):
        return "lib" + self.basename + ".so." + self.GetCurrentVersionBase()

    # returns the name of a shared library with a base version number
    def GetRawSharedLibraryName(self):
        return "lib" + self.basename + ".so"

    # Makes a symlink for the shared library in the specified directory (without trailing slash)
    def MakeSharedLibrarySymlink(self, env, destdir = "."):
        return SafeMakeSymlink(env, self.GetSharedLibraryName(), self.GetRawSharedLibraryName(), destdir)

    # Makes a symlink for the shared library in the specified directory (without trailing slash)
    def MakeBaseSharedLibrarySymlink(self, env, destdir = "."):
        return SafeMakeSymlink(env, self.GetSharedLibraryName(), self.GetBaseSharedLibraryName(), destdir)
