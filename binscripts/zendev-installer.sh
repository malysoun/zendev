#!/usr/bin/env bash

display_error() {
    tput sgr0
    tput setaf 1
    echo "ERROR: $1"
    tput sgr0
    exit 1
}

update_profile() {
    [ -f "$1" ] || return 1

    grep -F "$source_line" "$1" > /dev/null 2>&1
    if [ $? -ne 0 ]; then
	echo -e "\n$source_line" >> "$1"
    fi
}


BRANCH=zendev2
SRC_ROOT=${HOME}/src
ZENDEV_DEST=${SRC_ROOT}/github.com/zenoss
ZENDEV_DIR=${ZENDEV_DEST}/zendev
ZENDEV_REPO=git@github.com:zenoss/zendev.git


#TODO check zendev version for switch over from v1 to v2 (when zendev -v works)
if ! zendev -h  >/dev/null 2>&1 ; then
    echo "Installing zendev"

    [ -d "${ZENDEV_DIR}" ] && display_error "zendev already installed"
    [ -d "${ZENDEV_DEST}" ] || mkdir -p ${ZENDEV_DEST} > /dev/null 2>&1 || display_error "Failed to create ${ZENDEV_DEST}"

    if ! git --help > /dev/null 2>&1 ; then
	display_error "git not installed"
    fi

    git clone ${ZENDEV_REPO} ${ZENDEV_DIR} > /dev/null 2>&1 || display_error "Failed to clone from ${ZENDEV_REPO} into ${ZENDEV_DIR}"

    pushd . > /dev/null

    cd ${ZENDEV_DIR} && git checkout ${BRANCH} > /dev/null 2>&1
    pip install --user -e . || display_error "Failed to pip install zendev"
    popd > /dev/null

else
    echo "zendev already installed"
fi


ENV_FILE=${HOME}/.bashrc

update_profile ${HOME}/.bashrc
if [ "$(uname)" == "Darwin" ]; then
    ENV_FILE=${HOME}/.profile
fi

source_line='export PATH=${HOME}/bin:${HOME}/.local/bin:$PATH'
update_profile ${ENV_FILE}
source_line='source $(zendev bootstrap)'
update_profile ${ENV_FILE}

echo "Installing gvm"
bash < <(curl -s -S -L https://raw.githubusercontent.com/moovweb/gvm/master/binscripts/gvm-installer)

source ${HOME}/.gvm/scripts/gvm
gvm install go1.6.3 --binary
gvm install go1.4.3 --binary
gvm use go1.6.3 --default

echo "Installing hub"
GOPATH=${HOME} go get github.com/github/hub

if ! grep -F "#Setup hub completioN" ${ENV_FILE} > /dev/null 2>&1 ; then
    cat <<EOF>> ${ENV_FILE}
#Setup hub completion
if [ -f ${SRC_ROOT}/github.com/hub/etc/hub.bash_completion.sh ]; then
. ${SRC_ROOT}/github.com/hub/etc/hub.bash_completion.sh
fi
EOF
fi

echo "Installing jig"
GOPATH=${HOME} go get github.com/iancmcc/jig
