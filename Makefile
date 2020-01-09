#
#
#

all: check
	false

BUILDDEPS := flake8

build-dep:
	apt-get -y install $(BUILDDEPS)

check:
	flake8
