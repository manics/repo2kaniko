import setuptools

setuptools.setup(
    name="repo2kaniko",
    install_requires=["jupyter-repo2docker>=2023.6.0", "repo2podman>=0.2.0"],
    python_requires=">=3.8",
    author="Simon Li",
    url="https://github.com/manics/repo2kaniko",
    project_urls={"Documentation": "https://repo2docker.readthedocs.io"},
    keywords="reproducible science environments docker",
    description="Repo2docker Kaniko builder",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    use_scm_version={"write_to": "repo2kaniko/_version.py"},
    setup_requires=["setuptools_scm"],
    license="BSD",
    classifiers=[
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
    ],
    packages=setuptools.find_packages(),
    include_package_data=True,
    entry_points={
        "repo2docker.engines": ["kaniko = repo2kaniko.kaniko:KanikoEngine"],
    },
)
