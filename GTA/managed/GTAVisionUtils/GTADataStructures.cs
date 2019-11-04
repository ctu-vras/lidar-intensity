using System;
using System.Collections.Generic;
using System.Linq;
using GTA;
using MathNet.Numerics.LinearAlgebra;
using MathNet.Numerics.LinearAlgebra.Double;
using SharpDX;
using Vector3 = GTA.Math.Vector3;

namespace GTAVisionUtils
{
    public class GTARun
    {
        public Guid guid { get; set; }
        public int Id { get; set; }
    }

    public class GTABoundingBox2
    {
        public GTAVector2 Min { get; set; }
        public GTAVector2 Max { get; set; }

        public float Area => (Max.X - Min.X) * (Max.Y - Min.Y);
    }

    public enum DetectionType
    {
        background,
        person,
        car,
        bicycle
    }

    public enum DetectionClass
    {
        Unknown = -1,
        Compacts = 0,
        Sedans = 1,
        SUVs = 2,
        Coupes = 3,
        Muscle = 4,
        SportsClassics = 5,
        Sports = 6,
        Super = 7,
        Motorcycles = 8,
        OffRoad = 9,
        Industrial = 10,
        Utility = 11,
        Vans = 12,
        Cycles = 13,
        Boats = 14,
        Helicopters = 15,
        Planes = 16,
        Service = 17,
        Emergency = 18,
        Military = 19,
        Commercial = 20,
        Trains = 21
    }

    public class GTADetection
    {
        public GTADetection(Entity e, DetectionType type)
        {
            Type = type;
            Pos = new GTAVector(e.Position);
            Distance = Game.Player.Character.Position.DistanceTo(e.Position);
            BBox = GTAData.ComputeBoundingBox(e);
            Handle = e.Handle;

            Rot = new GTAVector(e.Rotation);
            velocity = new GTAVector(e.Velocity);
            cls = DetectionClass.Unknown;
            Vector3 gmin;
            Vector3 gmax;
            e.Model.GetDimensions(out gmin, out gmax);
            BBox3D = new BoundingBox((SharpDX.Vector3) new GTAVector(gmin), (SharpDX.Vector3) new GTAVector(gmax));
        }

        public GTADetection(Ped p) : this(p, DetectionType.person)
        {
        }

        public GTADetection(Vehicle v) : this(v, DetectionType.car)
        {
            cls = (DetectionClass) Enum.Parse(typeof(DetectionClass), v.ClassType.ToString());
        }

        public DetectionType Type { get; set; }
        public DetectionClass cls { get; set; }
        public GTAVector Pos { get; set; }
        public GTAVector Rot { get; set; }
        public float Distance { get; set; }
        public GTABoundingBox2 BBox { get; set; }
        public BoundingBox BBox3D { get; set; }
        public int Handle { get; set; }
        public GTAVector velocity { get; set; }
    }

    public class GTAVector
    {
        public GTAVector(Vector3 v)
        {
            X = v.X;
            Y = v.Y;
            Z = v.Z;
        }

        public float X { get; set; }
        public float Y { get; set; }
        public float Z { get; set; }

        public static explicit operator SharpDX.Vector3(GTAVector i)
        {
            return new SharpDX.Vector3(i.X, i.Y, i.Z);
        }
    }

    public class GTAVector2
    {
        public GTAVector2(float x, float y)
        {
            X = x;
            Y = y;
        }

        public float X { get; set; }
        public float Y { get; set; }
    }

    public class GTAData
    {
        public List<Weather> CapturedWeathers;
        public int Version { get; set; }
        public string ImageName { get; set; }
        public int ImageWidth { get; set; }
        public int ImageHeight { get; set; }
        public DateTime Timestamp { get; set; }
        public TimeSpan LocalTime { get; set; }
        public Weather CurrentWeather { get; set; }
        public GTAVector CamPos { get; set; }
        public GTAVector CamRot { get; set; }
        public BoundingBox CarModelBox { get; set; }

        public GTAVector CamDirection { get; set; }

        //mathnet's matrices are in heap storage, which is super annoying, 
        //but we want to use double matrices to avoid numerical issues as we
        //decompose the MVP matrix into seperate M,V and P matrices
        public DenseMatrix WorldMatrix { get; set; }
        public DenseMatrix ViewMatrix { get; set; }
        public DenseMatrix ProjectionMatrix { get; set; }
        public double CamFOV { get; set; }

        public double CamNearClip { get; set; }
        public double CamFarClip { get; set; }
        public GTAVector playerPos { get; set; }
        public GTAVector velocity { get; set; }
        public int UIHeight { get; set; }
        public int UIWidth { get; set; }
        public Guid sceneGuid { get; set; }
        public GTAVector CamRelativeRot { get; set; }
        public GTAVector CamRelativePos { get; set; }
        public GTAVector2 CurrentTarget { get; set; }

        public List<GTADetection> Detections { get; set; }

        public static GTABoundingBox2 ComputeBoundingBox(Entity e)
        {
            var m = e.Model;
            var rv = new GTABoundingBox2
            {
                Min = new GTAVector2(float.PositiveInfinity, float.PositiveInfinity),
                Max = new GTAVector2(float.NegativeInfinity, float.NegativeInfinity)
            };
            Vector3 gmin;
            Vector3 gmax;
            m.GetDimensions(out gmin, out gmax);
            var bbox = new BoundingBox((SharpDX.Vector3) new GTAVector(gmin), (SharpDX.Vector3) new GTAVector(gmax));

            var sp = ImageUtils.Convert3dTo2d(e.GetOffsetInWorldCoords(e.Position));
            foreach (var corner in bbox.GetCorners())
            {
                var c = new Vector3(corner.X, corner.Y, corner.Z);

                c = e.GetOffsetInWorldCoords(c);
                var s = ImageUtils.Convert3dTo2d(c);
                if (s.X == -1f || s.Y == -1f)
                {
                    rv.Min.X = float.PositiveInfinity;
                    rv.Max.X = float.NegativeInfinity;
                    rv.Min.Y = float.PositiveInfinity;
                    rv.Max.Y = float.NegativeInfinity;
                    return rv;
                }


                rv.Min.X = Math.Min(rv.Min.X, s.X);
                rv.Min.Y = Math.Min(rv.Min.Y, s.Y);
                rv.Max.X = Math.Max(rv.Max.X, s.X);
                rv.Max.Y = Math.Max(rv.Max.Y, s.Y);
            }

            return rv;
        }


        public static GTAData DumpData(string imageName, Weather capturedWeather)
        {
            return DumpData(imageName, new List<Weather> {capturedWeather});
        }

        public static GTAData DumpData(string imageName, List<Weather> capturedWeathers)
        {
            var ret = new GTAData();
            ret.Version = 3;
            ret.ImageName = imageName;
            ret.CurrentWeather = World.Weather;
            ret.CapturedWeathers = capturedWeathers;

            ret.Timestamp = DateTime.UtcNow;
            ret.LocalTime = World.CurrentDayTime;
            ret.CamPos = new GTAVector(World.RenderingCamera.Position);
            ret.CamRot = new GTAVector(World.RenderingCamera.Rotation);
            //getting information about currently driving vehicle model size
            Vector3 gmin;
            Vector3 gmax;
            Game.Player.Character.CurrentVehicle.Model.GetDimensions(out gmin, out gmax);
            ret.CarModelBox =
                new BoundingBox((SharpDX.Vector3) new GTAVector(gmin), (SharpDX.Vector3) new GTAVector(gmax));
            ret.CamDirection = new GTAVector(World.RenderingCamera.Direction);
            ret.CamFOV = World.RenderingCamera.FieldOfView;
            ret.ImageWidth = Game.ScreenResolution.Width;
            ret.ImageHeight = Game.ScreenResolution.Height;
            ret.UIWidth = UI.WIDTH;
            ret.UIHeight = UI.HEIGHT;
            ret.playerPos = new GTAVector(Game.Player.Character.Position);
            ret.velocity = new GTAVector(Game.Player.Character.Velocity);
            ret.CamNearClip = World.RenderingCamera.NearClip;
            ret.CamFarClip = World.RenderingCamera.FarClip;

            var peds = World.GetNearbyPeds(Game.Player.Character, 500.0f);
            var cars = World.GetNearbyVehicles(Game.Player.Character, 500.0f);
            //var props = World.GetNearbyProps(Game.Player.Character.Position, 300.0f);

            var constants = VisionNative.GetConstants();
            if (!constants.HasValue) return null;
            var W = MathNet.Numerics.LinearAlgebra.Single.DenseMatrix
                .OfColumnMajor(4, 4, constants.Value.world.ToArray()).ToDouble();
            var WV =
                MathNet.Numerics.LinearAlgebra.Single.DenseMatrix.OfColumnMajor(4, 4,
                    constants.Value.worldView.ToArray()).ToDouble();
            var WVP =
                MathNet.Numerics.LinearAlgebra.Single.DenseMatrix.OfColumnMajor(4, 4,
                    constants.Value.worldViewProjection.ToArray()).ToDouble();

            var V = WV * W.Inverse();
            var P = WVP * WV.Inverse();
            ret.ProjectionMatrix = P as DenseMatrix;
            ret.ViewMatrix = V as DenseMatrix;
            ret.WorldMatrix = W as DenseMatrix;

            var pedList = from ped in peds
                where ped.IsHuman && ped.IsOnFoot
//                where ped.IsHuman && ped.IsOnFoot && CheckVisible(ped)
                select new GTADetection(ped);
            var cycles = from ped in peds
                where ped.IsOnBike
//                where ped.IsOnBike && CheckVisible(ped)
                select new GTADetection(ped, DetectionType.bicycle);

            var vehicleList = from car in cars
//                where CheckVisible(car)
                select new GTADetection(car);
            ret.Detections = new List<GTADetection>();
            ret.Detections.AddRange(pedList);
            ret.Detections.AddRange(vehicleList);
            //ret.Detections.AddRange(cycles);

            return ret;
        }
    }
}