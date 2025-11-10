Repo for the OPTICAMQ Laser Maze Project:

The UI is run on the controller's Raspberry Pi using `LaserMazeController.py`. 
The schematic for the controller and Pi is found in `LaserMazeControllerSchematic.pdf`.

The associated i2c commands are stored in `opticamqfunclib.py`.

The arduinos which run the detectors and laser diodes have the `main_V8.ino` code saved to memory, this allows them to excute control functions on request (sent from the Pi via i2c). 
The schematic for the detector and arduino modules are found in  `LaserMazeDetectorsSchematic.pdf`
The encolsure schematics for the detectors is found in `LaserMaze_Detector_Enclosure.pdf`



