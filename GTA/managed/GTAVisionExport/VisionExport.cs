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
using VAutodrive;

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


        public static string Location;

        //this variable, when true, should be disabling car spawning and autodrive starting here, because offroad has different settings
        private static readonly bool GatheringData = true;
        private static readonly float Scale = 0.5f;

        //private readonly string dataPath =
        //    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "Data");
        private readonly string dataPath;
        private readonly int everyNth;

//        this is the vaustodrive keyhandling
        private readonly KeyHandling kh = new KeyHandling();

        private readonly bool useMultipleCameras = true; // when false, cameras handling script is not used at all

        private int curSessionId = -1;
        private bool enabled;
        private bool isGamePaused;

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
            UI.Notify("Logger initialized. Going to initialize cameras.");
            CamerasList.initialize();
            InitializeCameras();
            UI.Notify("VisionExport plugin initialized.");
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
                    UI.Notify("need reload game");
                    Wait(100);
                    ReloadGame();
                    break;
                case GameStatus.NeedStart:
                    Logger.WriteLine("Status is NeedStart");
                    StopRun();
                    ReloadGame();
                    Wait(100);
                    runTask?.Wait();
                    runTask = StartRun();
                    break;
                case GameStatus.NoActionNeeded:
                    break;
            }

            if (!runTask.IsCompleted) return;
            if (!postgresTask.IsCompleted) return;

            if (GatheringData && ticked == 0)
                try
                {
                    GamePause(true);
                    GatherData(5);
                    GamePause(false);
                }
                catch (Exception exception)
                {
                    GamePause(false);
                    Logger.WriteLine("exception occured, logging and continuing");
                    Logger.WriteLine(exception);
                }

            Game.TimeScale = 1f;
        }

        private void GatherData(int delay = 50)
        {
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
                    Wait(delay);
                    GatherDatForOneCamera(dateTimeFormat, guid);
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

            var weather = World.Weather;
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


            success = SaveSnapshotToFile(dat.ImageName);

            if (!success)
                return;

            PostgresExport.SaveSnapshot(dat, run.Id);
        }

        public GameStatus CheckStatus()
        {
            var player = Game.Player.Character;
            if (player.IsDead) return GameStatus.NeedReload;
            if (player.IsInVehicle())
            {
                var vehicle = player.CurrentVehicle;
                if (vehicle.Speed < 1.0f)
                {
                    //speed is in mph
                    if (LowSpeedTime.isPassed(Game.GameTime))
                    {
                        Logger.WriteLine("needed reload by low speed for 2 minutes");
                        UI.Notify("needed reload by low speed for 2 minutes");
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
                        UI.Notify("needed reload by staying in place 30 seconds");
                        return GameStatus.NeedReload;
                    }

                    if (NotMovingNorDrivingTime.isPassed(Game.GameTime))
                    {
                        Logger.WriteLine("starting driving from 6s inactivity");
                        UI.Notify("starting driving from 6s inactivity");
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

        public async Task StartSession()
        {
            var name = Guid.NewGuid().ToString();
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
            run = null;

            Game.Player.LastVehicle.Alpha = int.MaxValue;
        }

        public void GamePause(bool value)
        {
            //wraper for pausing and unpausing game, because if its paused, I don't want to pause it again and unpause it. 
            if (value != isGamePaused) Game.Pause(value);
            isGamePaused = value;
        }

        public static void EnterVehicle()
        {
            Model mod = null;
            mod = new Model(GTAConst.OnroadVehicleHash);

            var player = Game.Player;
            if (mod == null) UI.Notify("mod is null");

            if (player == null) UI.Notify("player is null");

            if (player.Character == null) UI.Notify("player.Character is null");

            UI.Notify("player position: " + player.Character.Position);
            var vehicle = World.CreateVehicle(mod, player.Character.Position);
            if (vehicle == null)
                UI.Notify("vehicle is null. Something is fucked up");
            else
                player.Character.SetIntoVehicle(vehicle, VehicleSeat.Driver);


            vehicle.Alpha = int.MaxValue;
            player.Character.Alpha = int.MaxValue;
        }

        public void ToggleNavigation()
        {
            var inf =
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


        public static void ClearStuckCheckers()
        {
            LowSpeedTime.clear();
            NotMovingTime.clear();
            NotMovingNorDrivingTime.clear();
            NearPointFromStart.clear();
            Logger.WriteLine("clearing checkers");
        }

        public void ReloadGame()
        {
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
                    break;
                case Keys.PageDown:
                    StopRun();
                    StopSession();
                    break;
                case Keys.F9:
                    World.Weather = World.Weather.Next();
                    break;
                case Keys.F10:
                    World.Weather = World.Weather.Prev();
                    break;
                case Keys.F11:
                    World.CurrentDayTime += new TimeSpan(1, 0, 0);
                    break;
                case Keys.F12:
                    World.CurrentDayTime -= new TimeSpan(1, 0, 0);
                    break;
            }
        }

        private bool SaveSnapshotToFile(string name)
        {
            var depth = VisionNative.GetDepthBuffer();
            var stencil = VisionNative.GetStencilBuffer();
            var color = VisionNative.GetColorBuffer();
            if (depth == null || stencil == null || color == null) return false;

            var res = Game.ScreenResolution;
            var fileName = Path.Combine(dataPath, name);
            ImageUtils.WriteToTiff(fileName, res.Width, res.Height, new List<byte[]> {color}, depth, stencil, false);
            return true;
        }
    }
}