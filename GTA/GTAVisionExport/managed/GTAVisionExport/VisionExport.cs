using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows.Forms;
using GTA;
using GTA.Math;
using GTA.Native;
using GTAVisionUtils;
using IniParser;

namespace GTAVisionExport
{
    internal class VisionExport : Script
    {
        public static string LogFilePath;
        private static readonly TimeChecker LowSpeedTime = new TimeChecker(TimeSpan.FromMinutes(20));
        private static readonly TimeChecker NotMovingTime = new TimeChecker(TimeSpan.FromSeconds(300));
        private static readonly TimeChecker NotMovingNorDrivingTime = new TimeChecker(TimeSpan.FromSeconds(60));

        private static readonly TimeNearPointChecker NearPointFromStart =
            new TimeNearPointChecker(TimeSpan.FromSeconds(60), 10, new Vector3());

        private static readonly TimeNotMovingTowardsPointChecker LongFarFromTarget =
            new TimeNotMovingTowardsPointChecker(TimeSpan.FromMinutes(2.5), new Vector2());

        private static bool _notificationsAllowed;
        public static string Location;

        //this variable, when true, should be disabling car spawning and autodrive starting here, because offroad has different settings
        private static readonly bool GatheringData = true;
        private static readonly float Scale = 0.5f;
        private readonly bool clearEverything = false;

        private readonly bool currentWeather = true;

        //private readonly string dataPath =
        //    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "Data");
        private readonly string dataPath;
        private readonly int everyNth;

        private readonly bool
            staticCamera = false; // this turns off whole car spawning, teleportation and autodriving procedure

        private readonly bool useMultipleCameras = true; // when false, cameras handling script is not used at all

        private readonly Weather wantedWeather = Weather.Clear;
        private int curSessionId = -1;
        private bool enabled;

//        this is the vaustodrive keyhandling
        private KeyHandling kh = new KeyHandling();

        private Task postgresTask;

        private GTARun run;

        private Task runTask;
        private int ticked;

        public VisionExport()
        {
            // loading ini file
            var parser = new FileIniDataParser();
            Location = AppDomain.CurrentDomain.BaseDirectory;
            var data = parser.ReadFile(Path.Combine(Location, "GTAVision.ini"));

            //UINotify(ConfigurationManager.AppSettings["database_connection"]);
            dataPath = data["Snapshots"]["OutputDir"];
            LogFilePath = data["Snapshots"]["LogFile"];
            everyNth = int.Parse(data["Snapshots"]["EveryNth"]);
            ticked = 0;
            Logger.logFilePath = LogFilePath;

            Logger.WriteLine("VisionExport constructor called.");
            if (!Directory.Exists(dataPath)) Directory.CreateDirectory(dataPath);
            PostgresExport.InitSQLTypes();
            Tick += OnTick;
            KeyDown += OnKeyDown;

            Interval = 100;
            if (enabled)
            {
                postgresTask?.Wait();
                postgresTask = StartSession();
                runTask?.Wait();
                runTask = StartRun();
            }

            Logger.WriteLine("Logger prepared");
            UINotify("Logger initialized. Going to initialize cameras.");
            CamerasList.initialize();
            InitializeCameras();
            UINotify("VisionExport plugin initialized.");
        }

        private void InitializeCameras()
        {
            CamerasList.setMainCamera();

            CamerasList.addCamera(new Vector3(0f, 0f, 2.5626f), new Vector3(0f, 0f, 0f), 65, 0.15f);
            CamerasList.addCamera(new Vector3(0f, 0f, 2.5626f), new Vector3(0f, 0f, 90f), 65, 0.15f);
            CamerasList.addCamera(new Vector3(0f, 0f, 2.5626f), new Vector3(0f, 0f, 180f), 65, 0.15f);
            CamerasList.addCamera(new Vector3(0f, 0f, 2.5626f), new Vector3(0f, 0f, 270f), 65, 0.15f);
        }

        public void OnTick(object o, EventArgs e)
        {
            ticked += 1;
            ticked %= everyNth;

            if (!enabled)
            {
                Game.TimeScale = 1f;
                return;
            }

            Game.TimeScale = Scale;

            switch (CheckStatus())
            {
                case GameStatus.NeedReload:
                    Logger.WriteLine("Status is NeedReload");
                    StopRun();
                    runTask?.Wait();
                    runTask = StartRun();
                    //StopSession();
                    //Autostart();
                    UINotify("need reload game");
                    Wait(100);
                    ReloadGame();
                    break;
                case GameStatus.NeedStart:
                    Logger.WriteLine("Status is NeedStart");
                    //Autostart();
                    // use reloading temporarily
                    StopRun();

                    ReloadGame();
                    Wait(100);
                    runTask?.Wait();
                    runTask = StartRun();
                    //Autostart();
                    break;
                case GameStatus.NoActionNeeded:
                    break;
            }

//            UINotify("runTask.IsCompleted: " + runTask.IsCompleted.ToString());
//            UINotify("postgresTask.IsCompleted: " + postgresTask.IsCompleted.ToString());
            if (!runTask.IsCompleted) return;
            if (!postgresTask.IsCompleted) return;

//            UINotify("going to save images and save to postgres");

            if (GatheringData && ticked == 0)
                try
                {
                    GamePause(true);
                    GatherData(0);
                    GamePause(false);
                }
                catch (Exception exception)
                {
                    GamePause(false);
                    Logger.WriteLine("exception occured, logging and continuing");
                    Logger.WriteLine(exception);
                }
        }

        private void GatherData(int delay = 50)
        {
            if (clearEverything) ClearSurroundingEverything(Game.Player.Character.Position, 1000f);

            Game.TimeScale = 0.005f;

            var dateTimeFormat = @"yyyy-MM-dd--HH-mm-ss--fff";
            var guid = Guid.NewGuid();
            Logger.WriteLine("generated scene guid: " + guid);

            if (useMultipleCameras)
            {
                for (var i = 0; i < CamerasList.cameras.Count; i++)
                {
                    Logger.WriteLine("activating camera " + i);
                    CamerasList.ActivateCamera(i);
                    GatherDatForOneCamera(dateTimeFormat, guid);
                    Wait(delay);
                }

                CamerasList.Deactivate();
            }
            else
            {
//                when multiple cameras are not used, only main camera is being used. 
//                now it checks if it is active or not, and sets it
                if (!CamerasList.mainCamera.IsActive) CamerasList.ActivateMainCamera();

                GatherDatForOneCamera(dateTimeFormat, guid);
            }

            Wait(delay);
        }

        private void GatherDatForOneCamera(string dateTimeFormat, Guid guid)
        {
            GTAData dat;
            bool success;

            var weather = currentWeather ? World.Weather : wantedWeather;
            dat = GTAData.DumpData(DateTime.UtcNow.ToString(dateTimeFormat), weather);

            if (CamerasList.activeCameraRotation.HasValue)
                dat.CamRelativeRot = new GTAVector(CamerasList.activeCameraRotation.Value);
            else
                dat.CamRelativeRot = null;

            if (CamerasList.activeCameraPosition.HasValue)
                dat.CamRelativePos = new GTAVector(CamerasList.activeCameraPosition.Value);
            else
                dat.CamRelativePos = null;

            dat.CurrentTarget = null;
            dat.sceneGuid = guid;

            if (dat == null) return;


            success = SaveSnapshotToFile(dat.ImageName, weather, false);

            if (!success)
                //                    when getting data and saving to file failed, saving to db is skipped
                return;

            PostgresExport.SaveSnapshot(dat, run.guid);
        }

        /* -1 = need restart, 0 = normal, 1 = need to enter vehicle */
        public GameStatus CheckStatus()
        {
            var player = Game.Player.Character;
            if (player.IsDead) return GameStatus.NeedReload;
            if (player.IsInVehicle())
            {
                var vehicle = player.CurrentVehicle;
//                here checking the time in low or no speed 
                if (vehicle.Speed < 1.0f)
                {
                    //speed is in mph
                    if (LowSpeedTime.isPassed(Game.GameTime))
                    {
                        Logger.WriteLine("needed reload by low speed for 2 minutes");
                        UINotify("needed reload by low speed for 2 minutes");
                        return GameStatus.NeedReload;
                    }
                }
                else
                {
                    LowSpeedTime.clear();
                }

                if (vehicle.Speed < 0.01f)
                {
                    if (NotMovingTime.isPassed(Game.GameTime))
                    {
                        Logger.WriteLine("needed reload by staying in place 30 seconds");
                        UINotify("needed reload by staying in place 30 seconds");
                        return GameStatus.NeedReload;
                    }
                    
                    if (NotMovingNorDrivingTime.isPassed(Game.GameTime))
                    {
                        Logger.WriteLine("starting driving from 6s inactivity");
                        UINotify("starting driving from 6s inactivity");
                    }
                }
                else
                {
                    NotMovingTime.clear();
                    NotMovingNorDrivingTime.clear();
                }

//                here checking the movement from previous position on some time
                if (NearPointFromStart.isPassed(Game.GameTime, vehicle.Position))
                {
                    Logger.WriteLine("vehicle hasn't moved for 10 meters after 1 minute");
                    return GameStatus.NeedReload;
                }

                return GameStatus.NoActionNeeded;
            }

            return GameStatus.NeedReload;
        }

        public async Task StartSession(string name = session_name)
        {
            if (name == null) name = Guid.NewGuid().ToString();
            if (curSessionId != -1) StopSession();
            var id = await PostgresExport.StartSession(name);
            curSessionId = id;
        }

        public void StopSession()
        {
            if (curSessionId == -1) return;
            PostgresExport.StopSession(curSessionId);
            curSessionId = -1;
        }

        public async Task StartRun(bool enable = true)
        {
            await postgresTask;
            if (run != null) PostgresExport.StopRun(run);
            var runid = await PostgresExport.StartRun(curSessionId);
            run = runid;
            if (enable) enabled = true;
        }

        public void StopRun()
        {
            runTask?.Wait();
            ImageUtils.WaitForProcessing();
            enabled = false;
            PostgresExport.StopRun(run);
//            UploadFile();
            run = null;

            Game.Player.LastVehicle.Alpha = int.MaxValue;
        }

        public static void UINotify(string message)
        {
            //just wrapper for UI.Notify, but lets us disable showing notifications ar all
            if (_notificationsAllowed) UI.Notify(message);
        }

        public void GamePause(bool value)
        {
            //wraper for pausing and unpausing game, because if its paused, I don't want to pause it again and unpause it. 
            if (!isGamePaused) Game.Pause(value);
        }

        public static void EnterVehicle()
        {
            /*
            var vehicle = World.GetClosestVehicle(player.Character.Position, 30f);
            player.Character.SetIntoVehicle(vehicle, VehicleSeat.Driver);
            */
            Model mod = null;
            mod = new Model(GTAConst.OnroadVehicleHash);

            var player = Game.Player;
            if (mod == null) UINotify("mod is null");

            if (player == null) UINotify("player is null");

            if (player.Character == null) UINotify("player.Character is null");

            UINotify("player position: " + player.Character.Position);
            var vehicle = World.CreateVehicle(mod, player.Character.Position);
            if (vehicle == null)
                UINotify("vehicle is null. Something is fucked up");
            else
                player.Character.SetIntoVehicle(vehicle, VehicleSeat.Driver);


            vehicle.Alpha = int.MaxValue;
            player.Character.Alpha = int.MaxValue;
        }

        public void ToggleNavigation()
        {
            MethodInfo inf =
                kh.GetType().GetMethod("AtToggleAutopilot", BindingFlags.NonPublic | BindingFlags.Instance);
            inf.Invoke(kh, new object[] {new KeyEventArgs(Keys.J)});
        }

        private void ClearSurroundingVehicles(Vector3 pos, float radius)
        {
            ClearSurroundingVehicles(pos.X, pos.Y, pos.Z, radius);
        }

        private void ClearSurroundingVehicles(float x, float y, float z, float radius)
        {
            Function.Call(Hash.CLEAR_AREA_OF_VEHICLES, x, y, z, radius, false, false, false, false);
        }

        private void ClearSurroundingEverything(Vector3 pos, float radius)
        {
            ClearSurroundingEverything(pos.X, pos.Y, pos.Z, radius);
        }

        private void ClearSurroundingEverything(float x, float y, float z, float radius)
        {
            Function.Call(Hash.CLEAR_AREA, x, y, z, radius, false, false, false, false);
        }

        public static void ClearStuckCheckers()
        {
            LowSpeedTime.clear();
            NotMovingTime.clear();
            NotMovingNorDrivingTime.clear();
            NearPointFromStart.clear();
            LongFarFromTarget.clear();
            triedRestartingAutodrive = false;
            Logger.WriteLine("clearing checkers");
        }

        public void ReloadGame()
        {
            if (staticCamera) return;

            ClearStuckCheckers();

            var player = Game.Player.Character;
            player.LastVehicle.Delete();


            player.Position = GTAConst.HighwayStartPos;
            ClearSurroundingVehicles(player.Position, 100f);
            ClearSurroundingVehicles(player.Position, 3f);
            // start a new run
            EnterVehicle();
            ToggleNavigation();
            LowSpeedTime.clear();
        }

        public void OnKeyDown(object o, KeyEventArgs k)
        {
            switch (k.KeyCode)
            {
                case Keys.PageUp:
                    postgresTask?.Wait();
                    postgresTask = StartSession();
                    runTask?.Wait();
                    runTask = StartRun();
                    UINotify("GTA Vision Enabled");
//                there is set weather, just for testing
                    World.Weather = wantedWeather;
                    break;
                case Keys.PageDown:
                    if (staticCamera) CamerasList.Deactivate();

                    StopRun();
                    StopSession();
                    UINotify("GTA Vision Disabled");
                    break;
                // temp modification
                case Keys.H:
                    EnterVehicle();
                    UINotify("Trying to enter vehicle");
                    ToggleNavigation();
                    break;
                // temp modification
                case Keys.Y:
                    ReloadGame();
                    break;
                // temp modification
                case Keys.X:
                    _notificationsAllowed = !_notificationsAllowed;
                    if (_notificationsAllowed)
                        UI.Notify("Notifications Enabled");
                    else
                        UI.Notify("Notifications Disabled");

                    break;
            }
        }

        private bool SaveSnapshotToFile(string name, Weather weather, bool manageGamePauses = true)
        {
//            returns true on success, and false on failure
            if (manageGamePauses) GamePause(true);

            World.TransitionToWeather(weather,
                0.0f);
            Wait(10);
            var depth = VisionNative.GetDepthBuffer();
            var stencil = VisionNative.GetStencilBuffer();
            var color = VisionNative.GetColorBuffer();
            if (depth == null || stencil == null || color == null) return false;


            if (manageGamePauses) GamePause(false);

            var res = Game.ScreenResolution;
            var fileName = Path.Combine(dataPath, name);
            ImageUtils.WriteToTiff(fileName, res.Width, res.Height, new List<byte[]> {color}, depth, stencil, false);
//            UINotify("file saved to: " + fileName);
            return true;
        }
    }
}