YOKER_FROM = ../yoker
-include ~/.yoker/Makefile

YOKER_TEST = uv run yoker-test

MODEL ?= glm-5.2:cloud

run:
	$(YOKER_TEST) --model $(MODEL) 2>&1


