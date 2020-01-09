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
	pylint3 -E *.py

# The full-strength pylint complains about a lot more items, so we
# use the -E errors-only option above for CI tests
pylint:
	pylint3 *.py
