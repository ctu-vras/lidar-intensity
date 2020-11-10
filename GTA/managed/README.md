# Overview

This is the managed portion of the gta vision export code. This gets information from the game's scripting interface and the native plugin and uploads it to a postgres (postgis) database.

## Requirements
* GTAVisionNative (runtime)
* ScriptHookV SDK
* ScriptHookVDotNet2
* VAutodrive
* others managed by nuget

## Building
First go through the refereces in visual studio and update the paths for the non-nuget dependencies. These dependencies will usually live in your GTAV ddirectory. Then simply build the GTAVisionExport project and copy the resulting files except ScriptHookVDotNet2.dll into {gtav directory}/scripts.

You will also need to download ScriptHookVDotNet2 and place it to the toplevel GTA directory. Also, you need to have GTAVision.ini in your {gtav directory}/scripts, sample one is provided here.

## Database config
In order the connect to the database the managed plugins needs to know your database information. 

For that, create `GTAVision.ini` file in your scripts directory with following content:
```ini
[Database]
ConnectionString=<npgsql connection string>
```

The format of the conenction can be found at http://www.npgsql.org/doc/connection-string-parameters.html

Example config for localhost:
```ini
[Database]
ConnectionString=Server=127.0.0.1;Port=5432;Database=postgres;User Id=postgres;Password=postgres;
```


### Dependencies setup
Make sure your PostgreSQL database is up.


### In-game settings
The plugin captures whole screen (including any messages), so make sure, you don't have anything you don't want to on your screen, especially HUD, map, phone, etc. You can turn it off in the game settings. Once the plugin is loaded, you can use F9/F10 to cycle through weathers and F11/F12 to cycle through time (F11 adds one hour to in-game time, F12 subtracts an hour). On PageUp, the plugin starts capturing data, on PageDown, the plugin is turned off.

If you are already in a car, it won't do anything on the startup (not even turning autodrive), so you either enter a car, turn on autodrive (J) and then turn on capturing data (PageUp), or when not in vehicle, then turn on capturing data (PageUp) and it will spawn you on a highway in a default car, and no cars will be closeby and starts driving. The location and type of the car are specified in GtaVisionExport/GameUtils.cs, class GTAConst

### Other notes
Data gathering, specifically grabbing data from GPU buffers, breaks when using multiple monitors, data gathering must run only on one monitor.