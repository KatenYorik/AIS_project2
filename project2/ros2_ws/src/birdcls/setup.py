from setuptools import setup

package_name = "birdcls"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/demo.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Kate",
    maintainer_email="khodarevaekaterina@gmail.com",
    description="Классификация поведения птиц и контроллер на ожидаемой свободной энергии",
    license="MIT",
    entry_points={
        "console_scripts": [
            "camera_publisher = birdcls.camera_publisher:main",
            "classifier_node = birdcls.classifier_node:main",
            "controller_node = birdcls.controller_node:main",
        ],
    },
)
