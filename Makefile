#
#
#

all: check
	false

BUILDDEPS := flake8

build-deps:
	apt-get -y install $(BUILDDEPS)

check:
	flake8

# Not checked by default because there are still lots of violations
pylint:
	pylint3 *.py
