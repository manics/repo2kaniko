#!/usr/bin/env python

import os
import requests


REGISTRY_URL = "http://" + os.getenv("REGISTRY_HOST", "localhost:5000")
AUTH = ("user", "password")

r = requests.get(f"{REGISTRY_URL}/v2/_catalog", auth=AUTH)
r.raise_for_status()
repositories = r.json()["repositories"]
print(f"Repositories: {repositories}")
assert sorted(repositories) == ["cache", "test-conda"]

r = requests.get(f"{REGISTRY_URL}/v2/test-conda/tags/list", auth=AUTH)
r.raise_for_status()
test_conda_tags = r.json()["tags"]
print(f"test-conda tags: {test_conda_tags}")
assert test_conda_tags == ["ci"]

r = requests.get(f"{REGISTRY_URL}/v2/cache/tags/list", auth=AUTH)
r.raise_for_status()
cache_tags = r.json()["tags"]
print(f"cache tags: {cache_tags}")
# Should all be hashes
assert all(len(c) == 64 for c in cache_tags)
assert len(cache_tags) > 4
