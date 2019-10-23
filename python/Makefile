DIR = datatools

.PHONY: build clean

build:
	python3 setup.py build_ext --inplace
	rm -rf build

clean:
	rm -rf $(wildcard $(DIR)/*.c)  $(wildcard $(DIR)/*.so) build
	find . -regex "\(.*__pycache__.*\|*.py[co]\)" -exec rm -rf {} +
