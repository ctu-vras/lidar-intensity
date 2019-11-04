using System;
using GTA.Math;
using GTA.Native;

namespace GTAVisionExport
{
    public class TimeChecker
    {
        public TimeChecker(TimeSpan interval)
        {
            /* Game.Gametime is in ms, so 1000000 ms = 16.6 min*/
            startTime = 0;
            initialized = false;
            this.interval = interval;
        }

        public int startTime { get; set; }
        public bool initialized { get; set; }
        public TimeSpan interval { get; set; }

        public void clear()
        {
            initialized = false;
        }

        public bool isPassed(int time)
        {
            //UI.Notify("last time" + this.gameTime);
            //UI.Notify("time now" + time);
            if (!initialized)
            {
                startTime = time;
                initialized = true;
                return false;
            }

            return time >= startTime + interval.TotalMilliseconds;
        }
    }

    public abstract class TimeDistanceChecker
    {
        public Vector3 center;
        public int distance;

        public TimeDistanceChecker(TimeSpan interval, int distance, Vector3 center)
        {
            /* Game.Gametime is in ms, so 1000000 ms = 16.6 min*/
            startTime = 0;
            initialized = false;
            this.interval = interval;
            this.center = center;
            this.distance = distance;
        }

        public int startTime { get; set; }
        public bool initialized { get; set; }
        public TimeSpan interval { get; set; }

        public void clear()
        {
            initialized = false;
        }

        public abstract bool isDistanceSatisfied(Vector3 position);

        public bool isPassed(int time, Vector3 position)
        {
            //UI.Notify("last time" + this.gameTime);
            //UI.Notify("time now" + time);
            if (!initialized)
            {
                startTime = time;
                initialized = true;
                center = position;
                return false;
            }

            if (time >= startTime + interval.TotalMilliseconds) return isDistanceSatisfied(position);
            return false;
        }
    }

    /// <summary>
    ///     Use to check if vehicle is stuck in some area for some time (e.g. has not moved 1 meter or more from position in
    ///     last minute)
    /// </summary>
    public class TimeNearPointChecker : TimeDistanceChecker
    {
        public TimeNearPointChecker(TimeSpan interval, int distance, Vector3 center) : base(interval, distance, center)
        {
        }

        public override bool isDistanceSatisfied(Vector3 position)
        {
            return position.DistanceTo(center) < distance;
        }
    }

    /// <summary>
    ///     Use to check if vehicle is stuck in some area for some time (e.g. has not come nearer to a location (not moving to
    ///     a target))
    /// </summary>
    public class TimeDistantFromPointChecker : TimeDistanceChecker
    {
        public TimeDistantFromPointChecker(TimeSpan interval, int distance, Vector3 center) : base(interval, distance,
            center)
        {
        }

        public override bool isDistanceSatisfied(Vector3 position)
        {
            return position.DistanceTo(center) > distance;
        }
    }

    /// <summary>
    ///     Use to check if vehicle is stuck in some area for some time (e.g. has not come nearer to a location (not moving to
    ///     a target))
    ///     Updates distance, checks if min distance is changing or not after some time.
    /// </summary>
    public class TimeNotMovingTowardsPointChecker
    {
        public float distance;
        public float minDistance;

        public TimeNotMovingTowardsPointChecker(TimeSpan interval, Vector2 center)
        {
            /* Game.Gametime is in ms, so 1000000 ms = 16.6 min*/
            startTime = 0;
            initialized = false;
            this.interval = interval;
            this.center = center;
            minDistance = float.MaxValue;
        }

        public int startTime { get; set; }
        public bool initialized { get; set; }
        public TimeSpan interval { get; set; }
        public Vector2 center { get; set; }

        public void clear()
        {
            initialized = false;
        }

        public bool isPassed(int time, Vector3 position)
        {
            //UI.Notify("last time" + this.gameTime);
            //UI.Notify("time now" + time);
            if (!initialized)
            {
                startTime = time;
                initialized = true;
                minDistance = float.MaxValue;
                return false;
            }

            distance = center.DistanceTo(new Vector2(position.X, position.Y));
            if (distance < minDistance)
            {
                minDistance = distance;
                startTime = time;
            }

            if (time >= startTime + interval.TotalMilliseconds) return distance > minDistance;
            return false;
        }
    }

    public enum GameStatus
    {
        NeedReload,
        NeedStart,
        NoActionNeeded
    }

    public class GTAConst
    {
        public static Vector3 HighwayStartPos = new Vector3(1209.5412f, -1936.0394f, 38.3709f);
        public static VehicleHash OnroadVehicleHash = VehicleHash.Asea;
    }

    public static class Extensions
    {
        public static T Next<T>(this T src) where T : struct
        {
            if (!typeof(T).IsEnum)
                throw new ArgumentException($"Argument {typeof(T).FullName} is not an Enum");

            var arr = (T[]) Enum.GetValues(src.GetType());
            var j = Array.IndexOf(arr, src) + 1;
            return j == arr.Length - 1 ? arr[1] : arr[j];
        }

        public static T Prev<T>(this T src) where T : struct
        {
            if (!typeof(T).IsEnum)
                throw new ArgumentException($"Argument {typeof(T).FullName} is not an Enum");

            var arr = (T[]) Enum.GetValues(src.GetType());
            var j = Array.IndexOf(arr, src) - 1;
            return j == 0 ? arr[arr.Length - 2] : arr[j];
        }
    }
}