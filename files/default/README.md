# Unit Testing

Make a python virtual environment, install the requirements with:

    mkvirtualenv hatool -p python2
    pip install -r test-requirements.txt

Run the tests

    coverage run test-neutron-ha-tool.py

Coverage report

    coverage report -i neutron-ha-tool.py
