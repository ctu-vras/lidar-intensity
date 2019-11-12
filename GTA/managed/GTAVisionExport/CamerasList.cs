using System;
using System.Collections.Generic;
using System.IO;
using GTA;
using GTA.Math;
using GTAVisionUtils;
using IniParser;
using MathNet.Numerics.LinearAlgebra;
using MathNet.Spatial.Euclidean;
using MathNet.Spatial.Units;

namespace GTAVisionExport
{
    public static class CamerasList
    {
        private static int? gameplayInterval;

//        public static Camera gameCam;
        private static bool initialized;
        public static Camera mainCamera { get; private set; }
        public static Vector3 mainCameraPosition { get; private set; }
        public static Vector3 mainCameraRotation { get; private set; }

        public static List<Camera> cameras { get; } = new List<Camera>();
        public static List<Vector3> camerasPositions { get; } = new List<Vector3>();
        public static List<Vector3> camerasRotations { get; } = new List<Vector3>();

        public static Vector3? activeCameraRotation { get; private set; }
        public static Vector3? activeCameraPosition { get; private set; }

        public static void initialize()
        {
            if (initialized) return;

            World.DestroyAllCameras();
            Logger.WriteLine("destroying all cameras at the beginning, to be clear");
            var parser = new FileIniDataParser();
            var data = parser.ReadFile(Path.Combine(VisionExport.Location, "GTAVision.ini"));
            gameplayInterval = Convert.ToInt32(data["MultiCamera"]["GameplayTimeAfterSwitch"]);

            initialized = true;
        }

        public static void setMainCamera(Vector3 position = new Vector3(), Vector3 rotation = new Vector3(),
            float? fov = null, float? nearClip = null)
        {
            if (!initialized)
                throw new Exception("not initialized, please, call CamerasList.initialize() method before this one");

            Logger.WriteLine("setting main camera");
            if (!fov.HasValue) fov = GameplayCamera.FieldOfView;
            if (!nearClip.HasValue) nearClip = World.RenderingCamera.NearClip;

            mainCamera = World.CreateCamera(position, rotation, fov.Value);
            mainCamera.NearClip = nearClip.Value;
            mainCameraPosition = position;
            mainCameraRotation = rotation;

            mainCamera.IsActive = false;
            World.RenderingCamera = null;
        }

        public static void addCamera(Vector3 position, Vector3 rotation, float? fov = null, float? nearClip = null)
        {
            if (!initialized)
                throw new Exception("not initialized, please, call CamerasList.initialize() method before this one");

            Logger.WriteLine("adding new camera");
            if (!fov.HasValue) fov = GameplayCamera.FieldOfView;
            if (!nearClip.HasValue) nearClip = World.RenderingCamera.NearClip;

            var newCamera = World.CreateCamera(new Vector3(), new Vector3(), fov.Value);
            newCamera.NearClip = nearClip.Value;
            cameras.Add(newCamera);
            camerasPositions.Add(position);
            camerasRotations.Add(rotation);
        }

        public static void ActivateMainCamera()
        {
            if (!initialized)
                throw new Exception("not initialized, please, call CamerasList.initialize() method before this one");

            if (mainCamera == null) throw new Exception("please, set main camera");

            mainCamera.IsActive = true;
            World.RenderingCamera = mainCamera;
            activeCameraRotation = mainCameraRotation;
            activeCameraPosition = mainCameraPosition;
        }

        public static Vector3 rotationMatrixToDegrees(Matrix<double> r)
        {
            var sy = Math.Sqrt(r[0, 0] * r[0, 0] + r[1, 0] * r[1, 0]);

            var singular = sy < 1e-6;

            var x = 0d;
            var y = 0d;
            var z = 0d;
            if (!singular)
            {
                x = Math.Atan2(r[2, 1], r[2, 2]);
                y = Math.Atan2(-r[2, 0], sy);
                z = Math.Atan2(r[1, 0], r[0, 0]);
            }
            else
            {
                x = Math.Atan2(-r[1, 2], r[1, 1]);
                y = Math.Atan2(-r[2, 0], sy);
                z = 0;
            }

            return new Vector3((float) Angle.FromRadians(x).Degrees, (float) Angle.FromRadians(y).Degrees,
                (float) Angle.FromRadians(z).Degrees);
        }

        public static Camera ActivateCamera(int i)
        {
            if (!initialized)
                throw new Exception("not initialized, please, call CamerasList.initialize() method before this one");

            if (i >= cameras.Count) throw new Exception("there is no camera with index " + i);

            Game.Pause(false);
            cameras[i].IsActive = true;
            World.RenderingCamera = cameras[i];
            cameras[i].AttachTo(Game.Player.Character.CurrentVehicle, camerasPositions[i]);

            // computing correct rotation
            var rot = Game.Player.Character.CurrentVehicle.Rotation;
            var rotX = Matrix3D.RotationAroundXAxis(Angle.FromDegrees(rot.X));
            var rotY = Matrix3D.RotationAroundYAxis(Angle.FromDegrees(rot.Y));
            var rotZ = Matrix3D.RotationAroundZAxis(Angle.FromDegrees(rot.Z));
            var rotMat = rotZ * rotY * rotX;
            var relRotX = Matrix3D.RotationAroundXAxis(Angle.FromDegrees(camerasRotations[i].X));
            var relRotY = Matrix3D.RotationAroundYAxis(Angle.FromDegrees(camerasRotations[i].Y));
            var relRotZ = Matrix3D.RotationAroundZAxis(Angle.FromDegrees(camerasRotations[i].Z));
            var relRotMat = relRotZ * relRotY * relRotX;
            var rotmatdeg = rotationMatrixToDegrees(rotMat * relRotMat);
            cameras[i].Rotation = rotmatdeg;
            Script.Wait(gameplayInterval.Value);
            Game.Pause(true);
            
            // computing position and rotation manually to be able to find diff
            rot = Game.Player.Character.CurrentVehicle.Rotation;
            rotX = Matrix3D.RotationAroundXAxis(Angle.FromDegrees(rot.X));
            rotY = Matrix3D.RotationAroundYAxis(Angle.FromDegrees(rot.Y));
            rotZ = Matrix3D.RotationAroundZAxis(Angle.FromDegrees(rot.Z));
            rotMat = rotZ * rotY * rotX;
            rotmatdeg = rotationMatrixToDegrees(rotMat * relRotMat);
            
            var vector = Vector<double>.Build.Dense(3);
            vector[0] = camerasPositions[i].X;
            vector[1] = camerasPositions[i].Y;
            vector[2] = camerasPositions[i].Z;
            var rotVec = rotMat * vector;
            var computed = new Vector3();
            computed.X = (float) rotVec[0];
            computed.Y = (float) rotVec[1];
            computed.Z = (float) rotVec[2];
            computed += Game.Player.Character.CurrentVehicle.Position;
            
            Logger.WriteLine("Computed camera position is: " + computed);
            Logger.WriteLine("New camera position is: " + World.RenderingCamera.Position);
            Logger.WriteLine("Computed camera rotation is: " + rotmatdeg);
            Logger.WriteLine("New camera rotation is: " + World.RenderingCamera.Rotation);
            activeCameraRotation = camerasRotations[i];
            activeCameraPosition = camerasPositions[i];
            return cameras[i];
        }

        public static void Deactivate()
        {
            if (!initialized)
                throw new Exception("not initialized, please, call CamerasList.initialize() method before this one");

            mainCamera.IsActive = false;
            foreach (var camera in cameras) camera.IsActive = false;

            World.RenderingCamera = null;
        }
    }
}