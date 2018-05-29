import json
import sys
import os
from git import Repo, GitCommandError
import docker


def checkout_git_repositories(spec, selected_repo):
    print("Checking out repositories...")
    username = os.environ["GITHUB_USERNAME"]
    usertoken = os.environ["GITHUB_TOKEN"]
    github_preamble = f"https://{username}:{usertoken}@github.com/"
    print("Creating output directory...")
    try:
        os.stat("./git_repos")
    except:
        os.mkdir("./git_repos")
    print("... output repository directory created.")

    for repo_config in spec["components"]:
        repository_name = repo_config['repository-name']

        if selected_repo is not "all" and repository_name != selected_repo:
            print(f"Skipping {repository_name} from checkout.")
            continue

        repository_url = github_preamble + repo_config['github-repository']
        repository_dest = "./git_repos/"+repo_config['repository-name']
        commit_id = repo_config['commit']

        print(f"Checking out {repository_name}")
        print(f"From GitHub repository {repo_config['github-repository']}")
        print(f"At commit {commit_id}")

        print("Cloning repository...")
        repo = Repo.clone_from(repository_url, repository_dest)
        print("... repository was cloned")

        print("Creating branch...")
        repo.head.reference = repo.create_head('baseline', commit_id)
        repo.head.reset(index=True, working_tree=True)
        print("... 'baseline' branch was created")

        if repo_config["use-nightly"] == True:
            nightly_url = github_preamble + repo_config["nightly-repository"]
            nightly_branch = repo_config["nightly-branch"]
            nightly_repo = repo.create_remote("nightly", nightly_url)

            print("Checking out nightly mirror repository...")
            print(
                f"From GitHub repository {repo_config['nightly-repository']}")
            print(f"At branch {nightly_branch}")

            nightly_repo.fetch()
            nightly_head = repo.create_head(
                'baseline-nightly', f"nightly/{nightly_branch}")
            repo.head.reference = nightly_head
            repo.head.reset(index=True, working_tree=True)
            print("... nightly mirror repository was cloned, branches updated.")
    print("... repositories were checked out.")


def merge_git_branches(spec, selected_repo):
    print("Merging branches from repositories with nightly mirrors...")
    for repo_config in spec["components"]:
        repository_name = repo_config['repository-name']

        if selected_repo is not "all" and repository_name != selected_repo:
            print(f"Skipping {repository_name} from merging.")
            continue

        repository_dest = "./git_repos/"+repo_config['repository-name']
        repo = Repo(repository_dest)
        baseline_head = repo.heads['baseline']

        if repo_config["use-nightly"] == True:
            nightly_head = repo.heads['baseline-nightly']
            repo.head.reference = nightly_head
            repo.head.reset(index=True, working_tree=True)
            print(f"Merging code from {repository_name}...")
            repo.git.merge(baseline_head)
            try:
                repo.git.commit(f"-m \"Merging from {repo_config['commit']}\"")
            except GitCommandError as error:
                if "nothing to commit, working tree clean" in error.stdout:
                    print("Worktree is clean")
                else:
                    print("Unrecoverable error: ")
                    print(f"{error}")
                    raise error
            print("... merge was committed.")
        else:
            print(f"Repository {repository_name} doesn't need merging.")
    print("... all repositories were merged.")


def create_git_tag(spec, selected_repo):
    print("Creating tag for all repositories...")
    baseline_tag_name = spec["tag"]
    for repo_config in spec["components"]:
        repository_name = repo_config['repository-name']

        if selected_repo is not "all" and repository_name != selected_repo:
            print(f"Skipping {repository_name} from creating tag.")
            continue

        repository_dest = "./git_repos/"+repo_config['repository-name']
        repo = Repo(repository_dest)
        baseline_head = repo.heads['baseline']

        print(f"Creating tag for repository {repository_name}...")
        print("Checking whether tag has already been created...")

        if (baseline_tag_name in repo.tags):
            print("... tag has been already created.")
            print(f"... skipping repository {repository_name}.")
            continue
        else:
            print("... tag is not created yet. Good to go.")

        if repo_config["use-nightly"] == True:
            nightly_head = repo.heads['baseline-nightly']

            print("Creating baseline tag...")
            repo.create_tag(baseline_tag_name, ref=nightly_head,
                            message=f"Baseline: {baseline_tag_name}")

            print("... baseline tag was created.")
            print(
                f"... repository {repository_name} was properly tagged (nightly).")
        else:
            print("Creating baseline tag...")
            repo.create_tag(baseline_tag_name, ref=baseline_head,
                            message=f"Baseline: {baseline_tag_name}")
            print("... baseline tag was created.")
            print(f"... repository {repository_name} was properly tagged.")
    print("... all repositories were tagged.")


def push_git_tag(spec, selected_repo):
    print("Pushing everything to GitHub...")
    baseline_tag_name = spec["tag"]
    for repo_config in spec["components"]:
        repository_name = repo_config['repository-name']

        if selected_repo is not "all" and repository_name != selected_repo:
            print(f"Skipping {repository_name} from pushing tag.")
            continue

        repository_dest = "./git_repos/"+repo_config['repository-name']
        repo = Repo(repository_dest)
        print(f"Pushing tag to repository {repository_name}...")

        if repo_config["use-nightly"] == True:
            nightly_branch = repo_config["nightly-branch"]
            nightly_head = repo.heads['baseline-nightly']

            print("Pushing changes to nightly mirror repository...")
            repo.git.push("nightly", f"{nightly_head}:{nightly_branch}")
            print("... changes were pushed to nightly mirror.")

            print("Pushing baseline tag...")
            baseline_tag = repo.tags[baseline_tag_name]
            repo.git.push("nightly", baseline_tag)
            print("... baseline tag was pushed to nightly mirror.")
        else:
            print("Pushing baseline tag...")
            baseline_tag = repo.tags[baseline_tag_name]
            repo.remotes.origin.push(baseline_tag)
            print("... baseline tag was pushed.")

        print(f"... all changes were pushed to {repository_name}.")
    print("... everything was pushed to GitHub.")


def create_docker_baseline(spec, selected_repo):
    client = docker.from_env()
    docker_username = os.environ["DOCKER_USERNAME"]
    docker_password = os.environ["DOCKER_PASSWORD"]
    print("Logging into Docker Hub...")
    client.login(docker_username, docker_password)
    print("... logged in.")
    for repo_config in spec["components"]:
        repository_name = repo_config['repository-name']

        if selected_repo is not "all" and repository_name != selected_repo:
            print(f"Skipping {repository_name} from pushing Docker images.")
            continue

        for docker_repo in repo_config["docker-hub-repositories"]:
            docker_name = docker_repo["name"]
            docker_tag = docker_repo["tag"]
            baseline_tag_name = spec["tag"]

            print(f"Pulling image {docker_name}:{docker_tag}...")
            image = client.images.pull(docker_name, tag=docker_tag)
            print("... image pulled.")
            print(f"Tagging it with {baseline_tag_name}...")
            image.tag(docker_name, tag=baseline_tag_name)
            print("... tagged.")
            print("Pushing new tag...")
            client.images.push(docker_name, tag=baseline_tag_name)
            print("... pushed.")


def main():
    print("Starting baseline builder...")

    print("Reading baseline spec file...")
    raw_spec = open("baseline-spec.json", "r")
    # Treat exceptions
    spec = json.loads(raw_spec.read())
    if len(sys.argv) != 3:
        checkout_git_repositories(spec, "all")
        create_git_tag(spec, "all")
        push_git_tag(spec, "all")
        create_docker_baseline(spec, "all")
    else:
        selected_repo = sys.argv[2]
        if sys.argv[1] == "checkout":
            checkout_git_repositories(spec, selected_repo)
        elif sys.argv[1] == "merge":
            merge_git_branches(spec, selected_repo)
        elif sys.argv[1] == "tag":
            create_git_tag(spec, selected_repo)
        elif sys.argv[1] == "push":
            push_git_tag(spec, selected_repo)
        elif sys.argv[1] == "docker":
            create_docker_baseline(spec, selected_repo)
        else:
            print("Unknown command.")


if __name__ == "__main__":
    main()
