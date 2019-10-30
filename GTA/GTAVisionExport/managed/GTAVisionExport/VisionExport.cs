using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using GTA;
using GTA.Math;
using GTA.Native;
using GTAVisionUtils;
using IniParser;
using Newtonsoft.Json;
using Color = System.Windows.Media.Color;

namespace GTAVisionExport
{
    internal class VisionExport : Script
    {
#if DEBUG
        private const string session_name = "NEW_DATA_CAPTURE_NATURAL_V4_3";
#else
        const string session_name = "NEW_DATA_CAPTURE_NATURAL_V4_3";
#endif
        //private readonly string dataPath =
        //    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "Data");
        private readonly string dataPath;
        public static string logFilePath;

        private readonly Weather[] wantedWeathers =
            {Weather.Clear, Weather.Clouds, Weather.Overcast, Weather.Raining, Weather.Christmas};

        private readonly Weather wantedWeather = Weather.Clear;
        private readonly bool currentWeather = true;
        private readonly bool clearEverything = false;
        private readonly bool useMultipleCameras = true; // when false, cameras handling script is not used at all

        private readonly bool
            staticCamera = false; // this turns off whole car spawning, teleportation and autodriving procedure

        private Player player;
        private GTARun run;
        private bool enabled;
        private readonly Socket server;
        private Socket connection;
        private readonly UTF8Encoding encoding = new UTF8Encoding(false);

//        this is the vaustodrive keyhandling
        private KeyHandling kh = new KeyHandling();

        private Task postgresTask;

        private Task runTask;
        private int curSessionId = -1;
        public static TimeChecker lowSpeedTime = new TimeChecker(TimeSpan.FromMinutes(20));
        public static TimeChecker notMovingTime = new TimeChecker(TimeSpan.FromSeconds(300));
        public static TimeChecker notMovingNorDrivingTime = new TimeChecker(TimeSpan.FromSeconds(60));

        public static TimeNearPointChecker NearPointFromStart =
            new TimeNearPointChecker(TimeSpan.FromSeconds(60), 10, new Vector3());

        public static TimeNotMovingTowardsPointChecker LongFarFromTarget =
            new TimeNotMovingTowardsPointChecker(TimeSpan.FromMinutes(2.5), new Vector2());

        private bool isGamePaused; // this is for external pause, not for internal pause inside the script
        private static bool notificationsAllowed;
        private bool timeIntervalEnabled;
        private TimeSpan timeFrom;
        private TimeSpan timeTo;
        public static string location;
        private static Vector2 somePos;

        //this variable, when true, should be disabling car spawning and autodrive starting here, because offroad has different settings
        public static bool gatheringData = true;
        public static bool triedRestartingAutodrive;
        private static readonly float scale = 0.5f;
        private readonly int everynth;
        private int ticked;

        public VisionExport()
        {
            // loading ini file
            var parser = new FileIniDataParser();
            location = AppDomain.CurrentDomain.BaseDirectory;
            var data = parser.ReadFile(Path.Combine(location, "GTAVision.ini"));

            //UINotify(ConfigurationManager.AppSettings["database_connection"]);
            dataPath = data["Snapshots"]["OutputDir"];
            logFilePath = data["Snapshots"]["LogFile"];
            everynth = int.Parse(data["Snapshots"]["EveryNth"]);
            ticked = 0;
            Logger.logFilePath = logFilePath;

            Logger.WriteLine("VisionExport constructor called.");
            if (!Directory.Exists(dataPath)) Directory.CreateDirectory(dataPath);
            PostgresExport.InitSQLTypes();
            player = Game.Player;
            server = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
            server.Bind(new IPEndPoint(IPAddress.Loopback, 5555));
            server.Listen(5);
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
            initializeCameras();
            UINotify("VisionExport plugin initialized.");
        }

        private void initializeCameras()
        {
            CamerasList.setMainCamera();

            CamerasList.addCamera(new Vector3(0f, 0f, 2.5626f), new Vector3(0f, 0f, 0f), 65, 0.15f);
            CamerasList.addCamera(new Vector3(0f, 0f, 2.5626f), new Vector3(0f, 0f, 90f), 65, 0.15f);
            CamerasList.addCamera(new Vector3(0f, 0f, 2.5626f), new Vector3(0f, 0f, 180f), 65, 0.15f);
            CamerasList.addCamera(new Vector3(0f, 0f, 2.5626f), new Vector3(0f, 0f, 270f), 65, 0.15f);
        }

        private void HandlePipeInput()
        {
            UINotify("server connected:" + server.Connected);
            UINotify(connection == null ? "connection is null" : "connection:" + connection);
            if (connection == null) return;

            var inBuffer = new byte[1024];
            var str = "";
            var num = 0;
            try
            {
                num = connection.Receive(inBuffer);
                str = encoding.GetString(inBuffer, 0, num);
            }
            catch (SocketException e)
            {
                if (e.SocketErrorCode == SocketError.WouldBlock) return;

                throw;
            }

            if (num == 0)
            {
                connection.Shutdown(SocketShutdown.Both);
                connection.Close();
                connection = null;
                return;
            }

            UINotify("str: " + str);
            Logger.WriteLine("obtained json: " + str);
            dynamic parameters = JsonConvert.DeserializeObject(str);
            string commandName = parameters.name;
            switch (commandName)
            {
                case "START_SESSION":
                    postgresTask?.Wait();
                    postgresTask = StartSession();
                    runTask?.Wait();
                    runTask = StartRun();
                    break;
                case "STOP_SESSION":
                    StopRun();
                    StopSession();
                    break;
                case "TOGGLE_AUTODRIVE":
                    ToggleNavigation();
                    break;
                case "ENTER_VEHICLE":
                    UINotify("Trying to enter vehicle");
                    EnterVehicle();
                    break;
                case "AUTOSTART":
                    Autostart();
                    break;
                case "RELOADGAME":
                    ReloadGame();
                    break;
                case "RELOAD":
                    var f = GetType()
                        .GetField("_scriptdomain", BindingFlags.NonPublic | BindingFlags.Instance);
                    var domain = f.GetValue(this);
                    var m = domain.GetType()
                        .GetMethod("DoKeyboardMessage", BindingFlags.Instance | BindingFlags.Public);
                    m.Invoke(domain, new object[] {Keys.Insert, true, false, false, false});
                    break;
                case "SET_TIME":
                    string time = parameters.time;
                    UINotify("starting set time, obtained: " + time);
                    var hoursAndMinutes = time.Split(':');
                    var hours = int.Parse(hoursAndMinutes[0]);
                    var minutes = int.Parse(hoursAndMinutes[1]);
                    World.CurrentDayTime = new TimeSpan(hours, minutes, 0);
                    UINotify("Time Set");
                    break;
                case "SET_WEATHER":
                    try
                    {
                        string weather = parameters.weather;
                        UINotify("Weather Set to " + weather);
                        var weatherEnum = (Weather) Enum.Parse(typeof(Weather), weather);
                        World.Weather = weatherEnum;
                    }
                    catch (Exception e)
                    {
                        Logger.WriteLine(e);
                    }

                    break;
                case "SET_TIME_INTERVAL":
                    string timeFrom = parameters.timeFrom;
                    string timeTo = parameters.timeTo;
                    UINotify("starting set time, obtained from: " + timeFrom + ", to: " + timeTo);
                    var hoursAndMinutesFrom = timeFrom.Split(':');
                    var hoursAndMinutesTo = timeTo.Split(':');
                    var hoursFrom = int.Parse(hoursAndMinutesFrom[0]);
                    var minutesFrom = int.Parse(hoursAndMinutesFrom[1]);
                    var hoursTo = int.Parse(hoursAndMinutesTo[0]);
                    var minutesTo = int.Parse(hoursAndMinutesTo[1]);
                    timeIntervalEnabled = true;
                    this.timeFrom = new TimeSpan(hoursFrom, minutesFrom, 0);
                    this.timeTo = new TimeSpan(hoursTo, minutesTo, 0);
                    UINotify("Time Interval Set");
                    break;
                case "PAUSE":
                    UINotify("game paused");
                    isGamePaused = true;
                    Game.Pause(true);
                    break;
                case "UNPAUSE":
                    UINotify("game unpaused");
                    isGamePaused = false;
                    Game.Pause(false);
                    break;
            }
        }

        public void startRunAndSessionManual()
        {
//            this method does not enable mod (used for manual data gathering)
            postgresTask?.Wait();
            postgresTask = StartSession();
            runTask?.Wait();
            runTask = StartRun(false);
        }

        public void OnTick(object o, EventArgs e)
        {
            ticked += 1;
            ticked %= everynth;
            if (server.Poll(10, SelectMode.SelectRead) && connection == null)
            {
                connection = server.Accept();
                UINotify("CONNECTED");
                connection.Blocking = false;
            }

            HandlePipeInput();
            if (!enabled)
            {
                Game.TimeScale = 1f;
                return;
            }

            Game.TimeScale = scale;


            //Array values = Enum.GetValues(typeof(Weather));


            switch (checkStatus())
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

            if (gatheringData && ticked == 0)
                try
                {
                    GamePause(true);
                    gatherData(0);
                    GamePause(false);
                }
                catch (Exception exception)
                {
                    GamePause(false);
                    Logger.WriteLine("exception occured, logging and continuing");
                    Logger.WriteLine(exception);
                }

//            if time interval is enabled, checkes game time and sets it to timeFrom, it current time is after timeTo
            if (timeIntervalEnabled)
            {
                var currentTime = World.CurrentDayTime;
                if (currentTime > timeTo) World.CurrentDayTime = timeFrom;
            }
        }

        private void gatherData(int delay = 50)
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
                    gatherDatForOneCamera(dateTimeFormat, guid);
                    Wait(delay);
                }

                CamerasList.Deactivate();
            }
            else
            {
//                when multiple cameras are not used, only main camera is being used. 
//                now it checks if it is active or not, and sets it
                if (!CamerasList.mainCamera.IsActive) CamerasList.ActivateMainCamera();

                gatherDatForOneCamera(dateTimeFormat, guid);
            }

            Wait(delay);
        }

        private void gatherDatForOneCamera(string dateTimeFormat, Guid guid)
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


            success = saveSnapshotToFile(dat.ImageName, weather, false);

            if (!success)
                //                    when getting data and saving to file failed, saving to db is skipped
                return;

            PostgresExport.SaveSnapshot(dat, run.guid);
        }

        /* -1 = need restart, 0 = normal, 1 = need to enter vehicle */
        public GameStatus checkStatus()
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
                    if (lowSpeedTime.isPassed(Game.GameTime))
                    {
                        Logger.WriteLine("needed reload by low speed for 2 minutes");
                        UINotify("needed reload by low speed for 2 minutes");
                        return GameStatus.NeedReload;
                    }
                }
                else
                {
                    lowSpeedTime.clear();
                }

                if (vehicle.Speed < 0.01f)
                {
                    if (notMovingTime.isPassed(Game.GameTime))
                    {
                        Logger.WriteLine("needed reload by staying in place 30 seconds");
                        UINotify("needed reload by staying in place 30 seconds");
                        return GameStatus.NeedReload;
                    }

//                    if (notMovingNorDrivingTime.isPassed(Game.GameTime) && !triedRestartingAutodrive) {
                    if (notMovingNorDrivingTime.isPassed(Game.GameTime))
                    {
                        Logger.WriteLine("starting driving from 6s inactivity");
                        UINotify("starting driving from 6s inactivity");
                    }
                }
                else
                {
                    notMovingTime.clear();
                    notMovingNorDrivingTime.clear();
                }

//                here checking the movement from previous position on some time
                if (NearPointFromStart.isPassed(Game.GameTime, vehicle.Position))
                {
                    Logger.WriteLine("vehicle hasn't moved for 10 meters after 1 minute");
                    return GameStatus.NeedReload;
                }

/*
                if (LongFarFromTarget.isPassed(Game.GameTime, vehicle.Position)) {
                    Logger.WriteLine("hasn't been any nearer to goal after 90 seconds");
                    return GameStatus.NeedReload;
                }
*/

                return GameStatus.NoActionNeeded;
            }

            return GameStatus.NeedReload;
        }

        public Bitmap CaptureScreen()
        {
            UINotify("CaptureScreen called");
            var cap = new Bitmap(Screen.PrimaryScreen.Bounds.Width, Screen.PrimaryScreen.Bounds.Height);
            var gfx = Graphics.FromImage(cap);
            //var dat = GTAData.DumpData(Game.GameTime + ".jpg");
            gfx.CopyFromScreen(0, 0, 0, 0, cap.Size);
            return cap;
        }

        public void Autostart()
        {
            if (!staticCamera)
            {
                EnterVehicle();
                Wait(200);
                ToggleNavigation();
                Wait(200);
            }

            postgresTask?.Wait();
            postgresTask = StartSession();
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
            if (notificationsAllowed) UI.Notify(message);
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


            vehicle.Alpha =
                int.MaxValue; //back to visible, not sure what the exact value means in terms of transparency
            player.Character.Alpha = int.MaxValue;
            vehicle.IsInvincible = true; //very important for offroad
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

        public static void clearStuckCheckers()
        {
            lowSpeedTime.clear();
            notMovingTime.clear();
            notMovingNorDrivingTime.clear();
            NearPointFromStart.clear();
            LongFarFromTarget.clear();
            triedRestartingAutodrive = false;
            Logger.WriteLine("clearing checkers");
        }

        public void ReloadGame()
        {
            if (staticCamera) return;

            clearStuckCheckers();

            /*
            Process p = Process.GetProcessesByName("Grand Theft Auto V").FirstOrDefault();
            if (p != null)
            {
                IntPtr h = p.MainWindowHandle;
                SetForegroundWindow(h);
                SendKeys.SendWait("{ESC}");
                //Script.Wait(200);
            }
            */
            // or use CLEAR_AREA_OF_VEHICLES
            var player = Game.Player.Character;
            //UINotify("x = " + player.Position.X + "y = " + player.Position.Y + "z = " + player.Position.Z);
            // no need to release the autodrive here
            // delete all surrounding vehicles & the driver's car
//            ClearSurroundingVehicles(player.Position, 1000f);
            player.LastVehicle.Delete();
            // teleport to the spawning position, defined in GameUtils.cs, subject to changes
//            player.Position = GTAConst.OriginalStartPos;

            player.Position = GTAConst.HighwayStartPos;
            ClearSurroundingVehicles(player.Position, 100f);
//            ClearSurroundingVehicles(player.Position, 50f);
//            ClearSurroundingVehicles(player.Position, 20f);
            ClearSurroundingVehicles(player.Position, 3f);
            // start a new run
            EnterVehicle();
            //Script.Wait(2000);
            ToggleNavigation();

            lowSpeedTime.clear();
        }

        public void TraverseWeather()
        {
            for (var i = 1; i < 14; i++)
                //World.Weather = (Weather)i;
                World.TransitionToWeather((Weather) i, 0.0f);
            //Script.Wait(1000);
        }

        public void OnKeyDown(object o, KeyEventArgs k)
        {
//            Logger.WriteLine("VisionExport OnKeyDown called.");
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
                    notificationsAllowed = !notificationsAllowed;
                    if (notificationsAllowed)
                        UI.Notify("Notifications Enabled");
                    else
                        UI.Notify("Notifications Disabled");

                    break;
                // temp modification
                case Keys.U:
                    var settings = ScriptSettings.Load("GTAVisionExport.xml");
                    var loc = AppDomain.CurrentDomain.BaseDirectory;

                    //UINotify(ConfigurationManager.AppSettings["database_connection"]);
                    var str = settings.GetValue("", "ConnectionString");
                    UINotify("BaseDirectory: " + loc);
                    UINotify("ConnectionString: " + str);
                    break;
                // temp modification
                case Keys.G:

                    GTAData data;

                    var weather = currentWeather ? World.Weather : wantedWeather;
                    data = GTAData.DumpData(Game.GameTime + ".tiff", weather);

                    var path = @"D:\GTAV_extraction_output\trymatrix.txt";
                    // This text is added only once to the file.
                    if (!File.Exists(path))
                        // Create a file to write to.
                        using (var file = File.CreateText(path))
                        {
                            file.WriteLine("cam direction file");
                            file.WriteLine("direction:");
                            file.WriteLine(
                                $"{World.RenderingCamera.Direction.X} {World.RenderingCamera.Direction.Y} {World.RenderingCamera.Direction.Z}");
                            file.WriteLine("Dot Product:");
                            file.WriteLine(Vector3.Dot(World.RenderingCamera.Direction,
                                World.RenderingCamera.Rotation));
                            file.WriteLine("position:");
                            file.WriteLine(
                                $"{World.RenderingCamera.Position.X} {World.RenderingCamera.Position.Y} {World.RenderingCamera.Position.Z}");
                            file.WriteLine("rotation:");
                            file.WriteLine(
                                $"{World.RenderingCamera.Rotation.X} {World.RenderingCamera.Rotation.Y} {World.RenderingCamera.Rotation.Z}");
                            file.WriteLine("relative heading:");
                            file.WriteLine(GameplayCamera.RelativeHeading.ToString());
                            file.WriteLine("relative pitch:");
                            file.WriteLine(GameplayCamera.RelativePitch.ToString());
                            file.WriteLine("fov:");
                            file.WriteLine(GameplayCamera.FieldOfView.ToString());
                        }

                    break;
                // temp modification
                case Keys.T:
                    World.Weather = Weather.Raining;
                    /* set it between 0 = stop, 1 = heavy rain. set it too high will lead to sloppy ground */
                    Function.Call(Hash._SET_RAIN_FX_INTENSITY, 0.5f);
                    var test = Function.Call<float>(Hash.GET_RAIN_LEVEL);
                    UINotify("" + test);
                    World.CurrentDayTime = new TimeSpan(12, 0, 0);
                    //Script.Wait(5000);
                    break;
                case Keys.N:
                    UINotify("N pressed, going to take screenshots");

                    startRunAndSessionManual();
                    postgresTask?.Wait();
                    runTask?.Wait();
                    UINotify("starting screenshots");
                    for (var i = 0; i < 2; i++)
                    {
                        GamePause(true);
                        gatherData(100);
                        GamePause(false);
                        Wait(200); // hoping game will go on during this wait
                    }

                    if (staticCamera) CamerasList.Deactivate();

                    StopRun();
                    StopSession();
                    break;
                case Keys.OemMinus: //to tlačítko vlevo od pravého shiftu, -
                    UINotify("- pressed, going to rotate cameras");

                    Game.Pause(true);
                    for (var i = 0; i < CamerasList.cameras.Count; i++)
                    {
                        Logger.WriteLine($"activating camera {i}");
                        CamerasList.ActivateCamera(i);
                        Wait(1000);
                    }

                    CamerasList.Deactivate();
                    Game.Pause(false);
                    break;
                case Keys.I:
                    var info = new InstanceData();
                    UINotify(info.type);
                    UINotify(info.publichostname);
                    break;
                case Keys.F12:
                    Logger.WriteLine(
                        $"{World.GetGroundHeight(Game.Player.Character.Position)} is the current player ({Game.Player.Character.Position}) ground position.");
                    Logger.WriteLine($"{World.GetGroundHeight(somePos)} is the {somePos} ground position.");
                    break;
                case Keys.F9:
                    //turn on and off for datagathering during driving, mostly for testing offroad
                    gatheringData = !gatheringData;
                    if (gatheringData)
                        UI.Notify("will be gathering data");
                    else
                        UI.Notify("won't be gathering data");

                    break;
            }
        }

        private bool saveSnapshotToFile(string name, Weather[] weathers, bool manageGamePauses = true)
        {
//            returns true on success, and false on failure
            var colors = new List<byte[]>();

            if (manageGamePauses) GamePause(true);

            var depth = VisionNative.GetDepthBuffer();
            var stencil = VisionNative.GetStencilBuffer();
            if (depth == null || stencil == null) return false;

            foreach (var wea in weathers)
            {
                World.TransitionToWeather(wea, 0.0f);
                Wait(1);
                var color = VisionNative.GetColorBuffer();
                if (color == null) return false;

                colors.Add(color);
            }

            if (manageGamePauses) GamePause(false);

            var res = Game.ScreenResolution;
            var fileName = Path.Combine(dataPath, name);
            ImageUtils.WriteToTiff(fileName, res.Width, res.Height, colors, depth, stencil, false);
//            UINotify("file saved to: " + fileName);
            return true;
        }

        private bool saveSnapshotToFile(string name, Weather weather, bool manageGamePauses = true)
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

        private void dumpTest()
        {
            var colors = new List<byte[]>();
            Game.Pause(true);
            Wait(1);
            var depth = VisionNative.GetDepthBuffer();
            var stencil = VisionNative.GetStencilBuffer();
            foreach (var wea in wantedWeathers)
            {
                World.TransitionToWeather(wea, 0.0f);
                Wait(1);
                colors.Add(VisionNative.GetColorBuffer());
            }

            Game.Pause(false);
            if (depth != null)
            {
                var res = Game.ScreenResolution;
                ImageUtils.WriteToTiff(Path.Combine(dataPath, "test"), res.Width, res.Height, colors, depth, stencil);
                UINotify(World.RenderingCamera.FieldOfView.ToString());
            }
            else
            {
                UINotify("No Depth Data quite yet");
            }

            UINotify((connection != null && connection.Connected).ToString());
        }
    }
}