from setuptools import setup, find_packages

setup(name='emuvim',
      version='0.0.1',
      license='Apache 2.0',
      description='emuvim is a VIM for the SONATA platform',
      url='http://github.com/sonata-emu',
      author_email='sonata-dev@sonata-nfv.eu',
      package_dir={'': 'src'},
      # packages=find_packages('emuvim', exclude=['*.test', '*.test.*', 'test.*', 'test']),
      packages=find_packages('src'),
      install_requires=[
          'pyaml',
          'zerorpc',
          'tabulate',
          'argparse',
          'networkx',
          'six>=1.9',
          'ryu',
          'ryu',
          'pytest',
          'Flask',
          'flask_restful',
          'docker-py==1.7.1',
          'requests',
          'prometheus_client',
          'paramiko',
          'urllib3'
      ],
      zip_safe=False,
      entry_points={
          'console_scripts': [
              'son-emu-cli=emuvim.cli.son_emu_cli:main',
          ],
      },
      setup_requires=['pytest-runner'],
      tests_require=['pytest'],
)
