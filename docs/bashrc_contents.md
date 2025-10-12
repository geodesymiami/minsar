.bashrc file contents:

```bash
# .bashrc

# Source global definitions
if [ -f /etc/bashrc ]; then
    . /etc/bashrc
fi

if [ -n "$SHELL_STARTUP_DEBUG" ]; then
  DBG_ECHO "${DBG_INDENT}}"
fi

modules_shell="bash"
[ -n module ] && module purge
umask 002

export USER_PREFERRED=""
export NOTIFICATIONEMAIL=""

export CPL_ZIP_ENCODING=UTF-8
export WORK2=${WORK2%/*}/stampede2

# User specific aliases and functions
shopt -s expand_aliases

alias s.bw2='export MINSAR_HOME=${WORK2%/*}/stampede2/code/minsar; source $MINSAR_HOME/setup/environment.bash; conda activate minsar'

```
(Sometimes the prompt shows `(base)` although you are in the `(minsar)` environment. Activating minsar before running s.bw2 may solve this. Use `which python` to make sure you are in the minsar environment. The `module` commands are only required for the pegasus system at RSMAS. The `umask` command gives others access to your files: everybody should be able to read/write in your scratch directory whereas nobody should be able to write in your home directory, but it is unclear whether this always works.  
