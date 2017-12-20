import dockerfile
import os
from abc import abstractmethod, ABCMeta
from glob import glob
from os import walk

from typing import List, Iterable, Set, Optional, TypeVar
from zgitignore import ZgitIgnore

DOCKER_IGNORE_FILE = ".dockerignore"

_FROM_DOCKER_COMMAND = "from"
_ADD_DOCKER_COMMAND = "add"
_RUN_DOCKER_COMMAND = "run"
_COPY_DOCKER_COMMAND = "copy"


class InvalidBuildConfigurationError(Exception):
    """
    Exception raised if a build configuration is invalid.
    """


class BuildConfiguration(metaclass=ABCMeta):
    """
    A configuration that describes how an item is built.
    """
    @property
    @abstractmethod
    def identifier(self) -> str:
        """
        Unique identifier of this configuration.
        :return: the identifier
        """

    @property
    @abstractmethod
    def requires(self) -> List[str]:
        """
        Other build configurations that this configuration is dependent on.
        :return: list of configurations
        """

    @property
    @abstractmethod
    def used_files(self) -> List[str]:
        """
        The files that this configuration to build an itme.
        :return: list of used files
        """

    def __str__(self) -> str:
        return self.identifier



BuildConfigurationType = TypeVar("BuildConfigurationType", bound=BuildConfiguration)


class DockerBuildConfiguration(BuildConfiguration):
    """
    A configuration that describes how a Docker image is built.
    """
    @property
    def identifier(self) -> str:
        return self._identifier

    @property
    def requires(self) -> List[str]:
        for command in self.commands:
            if command.cmd == _FROM_DOCKER_COMMAND:
                return command.value
        raise InvalidBuildConfigurationError(
            f"No \"{_FROM_DOCKER_COMMAND}\" command in dockerfile: {self.dockerfile_location}")

    @property
    def used_files(self) -> Iterable[str]:
        """
        Note: does not support adding URLs.
        """
        source_patterns: List[str] = []
        for command in self.commands:
            if command.cmd in [_ADD_DOCKER_COMMAND, _COPY_DOCKER_COMMAND]:
                assert len(command.value) >= 2
                source_patterns.extend(command.value[0:-1])

        source_files: Set[str] = set()
        for source_path in source_patterns:
            full_source_path = os.path.normpath(os.path.join(os.path.dirname(self.dockerfile_location), source_path))
            if os.path.isdir(full_source_path):
                candidate_files = glob(f"{full_source_path}/**/*", recursive=True)
            else:
                candidate_files = [full_source_path]

            for candidate_file in candidate_files:
                if os.path.exists(candidate_file) and not os.path.isdir(candidate_file):
                    source_files.add(candidate_file)

        return set(source_files - self.get_ignored_files())

    @property
    def from_image(self) -> str:
        """
        The image that the one built with this configuration is based off.
        :return: the parent image
        """
        assert len(self.requires) == 1
        return self.requires[0]

    @property
    def dockerfile_location(self) -> Optional[str]:
        return self._dockerfile_location

    @property
    def context(self) -> str:
        return self._context

    def __init__(self, image_name: str, dockerfile_location: str, context: str=None):
        """
        Constructor.
        :param image_name: name of the image built by this configuration (becomes its identifier)
        :param dockerfile_location: the location of the Dockerfile that describes how the image is built
        :param context: context in which the image is built
        """
        self._identifier = image_name
        self._dockerfile_location = dockerfile_location
        self._context = context if context is not None else os.path.dirname(self.dockerfile_location)
        self.commands = dockerfile.parse_file(self.dockerfile_location)

    def get_ignored_files(self) -> Set[str]:
        """
        Gets the files in the context that are ignored as per the .dockerignore file.
        :return: ignored files
        """
        ignored_files = set()
        dockerignore_path = os.path.join(os.path.dirname(self.dockerfile_location), DOCKER_IGNORE_FILE)
        if not os.path.exists(dockerignore_path):
            return ignored_files
        with open(dockerignore_path, "r") as file:
            ignored_patterns = [line.strip() for line in file.readlines()]

        # Note: not using glob as it ignores hidden files
        context_files: List[str] = []
        for path, directories, file_names in walk(self.context):
            for file_name in file_names:
                context_files.append(os.path.join(path, file_name))

        # ZGitIgnore roughly implements the same parsing of .dockerignore files as Docker:
        # https://docs.docker.com/engine/reference/builder/#dockerignore-file
        ignored_checker = ZgitIgnore(ignored_patterns)

        for context_file in context_files:
            relative_file_path = os.path.relpath(context_file, self.context)
            if ignored_checker.is_ignored(relative_file_path):
                ignored_files.add(context_file)

        return ignored_files
