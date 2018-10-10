# Python Plugin Engine
The plugin engine used for running python plugins in https://imjoy.io

## Installation
  Download the latest ImJoyApp [here](https://github.com/oeway/ImJoy-Python/releases).

  Follow the instructions according to different operating systems.

## Installation (alternative solution)
  If you you have trouble in using the above ImJoyApp, do the following:
  * Download and install [Miniconda with Python 3.7](https://conda.io/miniconda.html) (or [Anaconda with Python 3.6](https://www.anaconda.com/download/) if you prefer a full installation). If you have installed any of these, please skip this step.
  * Start a **Terminal**(Mac and Linux) or **Anaconda Prompt**(Windows), then run the following command:

    ```conda -V && pip install -U git+https://github.com/oeway/ImJoy-Python#egg=imjoy```
  * If you encountered any error related to `git` or `pip`, try to run : `conda install -y git pip` before the above command. (Otherwise, please check **FAQs**.)
  * You can also use the same command if you want to upgrade the Plugin Engine to the latest version.

  To use it after the installation:
  * Run `python -m imjoy` in a **Terminal** or **Anaconda Prompt**, and keep the window running.
  * Go to https://imjoy.io, connect to the plugin engine. For the first time, you will be asked to fill a token generated by the plugin engine from the previous step.
  * Now you can start to use plugins written in Python.

## Going offline
  ImJoy is designed to be offline ready, the engine serve a mirror site of ImJoy.IO locally. In order to do that, you need to first start the Python Plugin Engine by adding `--serve` in the command line:
  ```
  python -m imjoy --serve
  ```
Once it's done, you will be able to access your personal ImJoy web app through: [http://127.0.0.1:8080](http://127.0.0.1:8080).

Also notice that, although the main ImJoy app can go offline, and most of the plugins support offline, there still plugins require remote access to files, in that case, you won't be able to use those plugins without internet.

## Use the engine remotely.
You can use the Plugin Engine remotely on another computer. Due to security restrictions enforced by the browser, you won't be able to connect your remote plugin engine with https://imjoy.io , however, you can do it with the offline version of ImJoy. In addition to the instructions in **Go Offline**, you need to specify the host in order to allow outside connection:
```
  python -m imjoy --serve --host=0.0.0.0
```
Then go to http://IP_OF_YOUR_REMOTE:8080 to connect to the offline ImJoy. Then click the settings button, and you will be able set a remote url for the remote access.

## Running without conda
The recommended way of using the plugin engine is using a `conda` environment, however, in case you cannot use a conda environment, it is also possible to launch it. However, you will need at least a `Python 3` and solve all the dependencies yourself. To use it following the instructions in the `Freeze the environment` below.

## Freeze the environment

By default, the plugin engine will try to use `conda` to solve all the requirements and create virtual environments automatically. In some cases, if `conda` is not available, or for security reasons you want to disable this feature, you can pass `--freeze` parameter when running the plugin engine. For example `python -m imjoy --freeze` this will disable all the `conda` and `pip` commands. And this will reduce the plugin startup time and make it more stable.

However, in this case, you need to solve the dependencies yourself.


If you used the ImJoyApp we provided in the [releases](https://github.com/oeway/ImJoy-Python/releases), you can launch it manually.
For Linux and Mac, launch the following command in a Terminal:
```
# use the libraries in ImJoyApp
export PATH=~/ImJoyApp/bin:$PATH

# normal usage
python -m imjoy

# frozen mode
python -m imjoy --freeze


```

For Windows, search `powershell`, and run the following command:
```
# normal usage
$env:Path = '%systemdrive%%homepath%\ImJoyApp;%systemdrive%%homepath%\ImJoyApp\Scripts;' + $env:Path; python -m imjoy

# frozen mode
$env:Path = '%systemdrive%%homepath%\ImJoyApp;%systemdrive%%homepath%\ImJoyApp\Scripts;' + $env:Path; python -m imjoy --freeze
```

## FAQs
 * Can I use my existing python?

  It depends whether it's a conda-compatible distribution or not, try to type `conda -V` command, if you see a version number(e.g:`conda 4.3.30`), it means you can skip the Anaconda/Miniconda installation, and install ImJoy directly with your existing python.
 * Can I use ImJoy with Python 2.7 or other version lower than Python 3.6?

  Yes, you can if you have the conda environment. You will be able to install and run ImJoy with Python version lower thant 3.6 (e.g.: Anaconda/Miniconda Python2.7). However, in that case, it will bootstrapping itself by creating a Python 3 environment (named `imjoy`) in order to run the actual plugin engine code. Therefore, Anaconda/Miniconda (Python3.6+ version) is still recommended if you have the choice.
 * What's the difference with [Anaconda](https://www.anaconda.com/download/) and [Miniconda](https://conda.io/miniconda.html)?

 Miniconda is just a reduced version of Anaconda. Since ImJoy only relies on `conda` which included by both, you can choose either of them. If you like minimal installation, choose Miniconda. If you want all those packages which will be used for scientific computing(such as numpy, scipy, scikit-image etc.), choose Anaconda.
 * Why I can't connect to my plugin engine run on a remote computer?

 First, you needs to make sure the other computer with plugin engine can be accessed from your current network and not blocked by a firewall for example.

 Second, currently you can't use ImJoy.io loaded with `https` with the Plugin Engine, because modern browsers do not allow you to make a insecured connection within a SSL secured website. So, you will have to switch to the offline version.

 * Getting "address already in use error"?

 If you something like this: `OSError: [Errno 48] error while attempting to bind on address ('127.0.0.1', 8080): address already in use`, It means you have another instance which is using the the port needed by the Plugin Engine. You need to find it out and kill that task if you don't known which one. For example, for port `8080`, you can run `lsof -n -i :8082 | grep LISTEN` in a terminal and you will find the pid of the process which occuping the port, support the pid is `27762`, then you can run `kill 27762` to kill it.

 * CommandNotFoundError with 'conda activate'

 By default, ImJoy uses `conda activate` to activate conda environments if it's available. However, you may need to setup `conda activate` according to here: https://github.com/conda/conda/releases/tag/4.4.0

## Developing Python Plugins for ImJoy

See here for details: https://github.com/oeway/ImJoy
