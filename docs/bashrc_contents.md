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

alias s.bw2='export MINSAR_HOME=${WORK2%/*}/stampede2/code/minsar; unset PIXI_IN_SHELL PIXI_PROJECT_NAME; source $MINSAR_HOME/setup/environment.bash; conda activate minsar'

export INSARMAPSHOST_OLDDATA=149.165.153.50          
export INSARMAPSHOST_RECENTDATA=insarmaps.miami.edu
export INSARMAPSHOST_RECENTDATA=149.165.153.50           # overwrites to always use 149.165.153.50

```

(The `umask` command gives others access to your files: everybody should be able to read/write in your scratch directory whereas nobody should be able to write in your home directory, but it is unclear whether this always works.
