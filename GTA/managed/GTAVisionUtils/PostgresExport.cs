using System;
using System.IO;
using System.Threading.Tasks;
using GTA;
using IniParser;
using Npgsql;
using Npgsql.NameTranslation;
using NpgsqlTypes;

namespace GTAVisionUtils
{
    public class PostgresExport
    {
        public static void InitSQLTypes()
        {
            NpgsqlConnection.MapEnumGlobally<Weather>("weather", new NpgsqlNullNameTranslator());
            NpgsqlConnection.MapEnumGlobally<DetectionType>();
            NpgsqlConnection.MapEnumGlobally<DetectionClass>("detection_class",
                new NpgsqlNullNameTranslator());
        }

        public static NpgsqlConnection OpenConnection()
        {
            var parser = new FileIniDataParser();
            var location = AppDomain.CurrentDomain.BaseDirectory;
            var data = parser.ReadFile(Path.Combine(location, "GTAVision.ini"));
            
            var str = data["Database"]["ConnectionString"];

            var conn = new NpgsqlConnection(str);
            conn.Open();
            return conn;
        }

        public static async Task<int> StartSession(string name)
        {
            return await Task.Run(() => StartSessionImpl(name));
        }

        public static int StartSessionImpl(string name)
        {
            var conn = OpenConnection();
            var result = 0;
            using (var cmd = new NpgsqlCommand())
            {
                cmd.Connection = conn;
                cmd.CommandText = "INSERT INTO sessions (name, start) VALUES (@name, @start) ON CONFLICT DO NOTHING";
                cmd.Parameters.AddWithValue("@name", name);
                cmd.Parameters.AddWithValue("@start", DateTime.UtcNow);
                cmd.ExecuteNonQuery();
                cmd.CommandText = "SELECT session_id FROM sessions WHERE name = @name";
                result = (int) cmd.ExecuteScalar();
            }

            conn.Close();
            return result;
        }

        public static async Task StopSession(int sessionid)
        {
            await Task.Run(() => StopSessionImpl(sessionid));
        }

        public static void StopSessionImpl(int sessionid)
        {
            var conn = OpenConnection();
            using (var cmd = new NpgsqlCommand())
            {
                cmd.Connection = conn;
                cmd.CommandText = @"UPDATE sessions SET ""end"" = @endtime WHERE session_id = @sessionid";
                cmd.Parameters.AddWithValue("@endtime", DateTime.UtcNow);
                cmd.Parameters.AddWithValue("@sessionid", sessionid);
                cmd.ExecuteNonQuery();
            }

            conn.Close();
        }

        public static async Task<GTARun> StartRun(int sessionid)
        {
            var t = Task.Run(() => StartRunImpl(sessionid));
            return await t;
        }

        public static GTARun StartRunImpl(int sessionid)
        {
            var run = new GTARun();
            run.guid = Guid.NewGuid();
            var conn = OpenConnection();
            using (var cmd = new NpgsqlCommand())
            {
                cmd.Connection = conn;
                cmd.CommandText =
                    "INSERT INTO runs (runguid, session_id) VALUES (@guid, @session);";
                cmd.Parameters.AddWithValue("@guid", run.guid);
                cmd.Parameters.AddWithValue("@session", sessionid);
                cmd.ExecuteNonQuery();
                cmd.CommandText =  "SELECT run_id FROM runs WHERE runguid = @guid";
                run.Id = (int) cmd.ExecuteScalar();

            }

            conn.Close();

            return run;
        }

        public static void StopRun(GTARun run)
        {
        }

        public static async void SaveSnapshot(GTAData data, int runId)
        {
            await Task.Run(() => SaveSnapshotImpl(data, runId));
        }

        public static void SaveSnapshotImpl(GTAData data, int runId)
        {
            var conn = OpenConnection();
            var trans = conn.BeginTransaction();

            using (var cmd = new NpgsqlCommand())
            {
                var camRelativeRotString = "NULL";
                if (data.CamRelativeRot != null)
                {
                    camRelativeRotString = "ST_MakePoint(@relative_rot_x, @relative_rot_y, @relative_rot_z)";
                    cmd.Parameters.AddWithValue("@relative_rot_x", data.CamRelativeRot.X);
                    cmd.Parameters.AddWithValue("@relative_rot_y", data.CamRelativeRot.Y);
                    cmd.Parameters.AddWithValue("@relative_rot_z", data.CamRelativeRot.Z);
                }

                var camRelativePosString = "NULL";
                if (data.CamRelativePos != null)
                {
                    camRelativePosString = "ST_MakePoint(@relative_pos_x, @relative_pos_y, @relative_pos_z)";
                    cmd.Parameters.AddWithValue("@relative_pos_x", data.CamRelativePos.X);
                    cmd.Parameters.AddWithValue("@relative_pos_y", data.CamRelativePos.Y);
                    cmd.Parameters.AddWithValue("@relative_pos_z", data.CamRelativePos.Z);
                }

                var carModelBoxString = "NULL";
                if (data.CarModelBox != null)
                {
                    carModelBoxString = "ST_3DMakeBox(ST_MakePoint(@cam_box_min_x, @cam_box_min_y, @cam_box_min_z), " +
                                        "ST_MakePoint(@cam_box_max_x, @cam_box_max_y, @cam_box_max_z))";
                    cmd.Parameters.AddWithValue("@cam_box_min_x", data.CarModelBox.Minimum.X);
                    cmd.Parameters.AddWithValue("@cam_box_min_y", data.CarModelBox.Minimum.Y);
                    cmd.Parameters.AddWithValue("@cam_box_min_z", data.CarModelBox.Minimum.Z);
                    cmd.Parameters.AddWithValue("@cam_box_max_x", data.CarModelBox.Maximum.X);
                    cmd.Parameters.AddWithValue("@cam_box_max_y", data.CarModelBox.Maximum.Y);
                    cmd.Parameters.AddWithValue("@cam_box_max_z", data.CarModelBox.Maximum.Z);
                }

                var currentTarget = "NULL";
                if (data.CurrentTarget != null)
                {
                    currentTarget = "ST_MakePoint(@target_x, @target_y)";
                    cmd.Parameters.AddWithValue("@target_x", data.CurrentTarget.X);
                    cmd.Parameters.AddWithValue("@target_y", data.CurrentTarget.Y);
                }

                cmd.Connection = conn;
                cmd.Transaction = trans;
                cmd.CommandText =
                    "INSERT INTO snapshots (run_id, version, imagepath, timestamp, timeofday, currentweather, camera_pos, " +
                    "camera_rot, camera_direction, camera_fov, view_matrix, proj_matrix, width, height, ui_width, ui_height, " +
                    "player_pos, cam_near_clip, cam_far_clip, velocity, scene_id, camera_relative_rotation, " +
                    "camera_relative_position, car_model_box, world_matrix, current_target) VALUES ( @runid, @Version, " +
                    "@Imagepath, @Timestamp, @Timeofday, @currentweather, ST_MakePoint(@x, @y, @z), " +
                    "ST_MakePoint(@rotx, @roty, @rotz), ST_MakePoint(@dirx, @diry, @dirz), @fov, @view_matrix, @proj_matrix, " +
                    "@width, @height, @ui_width, @ui_height, ST_MakePoint(@player_x, @player_y, @player_z), @cam_near_clip, " +
                    $"@cam_far_clip, ST_MakePoint(@vel_x, @vel_y, @vel_z), @scene_id, {camRelativeRotString}, " +
                    $"{camRelativePosString}, {carModelBoxString}, @world_matrix, {currentTarget}) RETURNING snapshot_id;";
                cmd.Parameters.AddWithValue("@runid", runId);
                cmd.Parameters.AddWithValue("@version", data.Version);
                cmd.Parameters.AddWithValue("@imagepath", data.ImageName);
                cmd.Parameters.AddWithValue("@timestamp", data.Timestamp);
                cmd.Parameters.AddWithValue("@timeofday", data.LocalTime);
                cmd.Parameters.AddWithValue("@currentweather", data.CurrentWeather);
                cmd.Parameters.AddWithValue("@x", data.CamPos.X);
                cmd.Parameters.AddWithValue("@y", data.CamPos.Y);
                cmd.Parameters.AddWithValue("@z", data.CamPos.Z);
                cmd.Parameters.AddWithValue("@rotx", data.CamRot.X);
                cmd.Parameters.AddWithValue("@roty", data.CamRot.Y);
                cmd.Parameters.AddWithValue("@rotz", data.CamRot.Z);
                cmd.Parameters.AddWithValue("@dirx", data.CamDirection.X);
                cmd.Parameters.AddWithValue("@diry", data.CamDirection.Y);
                cmd.Parameters.AddWithValue("@dirz", data.CamDirection.Z);
                cmd.Parameters.AddWithValue("@fov", data.CamFOV);
                cmd.Parameters.AddWithValue("@view_matrix", data.ViewMatrix.ToArray());
                cmd.Parameters.AddWithValue("@proj_matrix", data.ProjectionMatrix.ToArray());
                cmd.Parameters.AddWithValue("@world_matrix", data.WorldMatrix.ToArray());
                cmd.Parameters.AddWithValue("@width", data.ImageWidth);
                cmd.Parameters.AddWithValue("@height", data.ImageHeight);
                cmd.Parameters.AddWithValue("@ui_width", data.UIWidth);
                cmd.Parameters.AddWithValue("@ui_height", data.UIHeight);
                cmd.Parameters.AddWithValue("@player_x", data.playerPos.X);
                cmd.Parameters.AddWithValue("@player_y", data.playerPos.Y);
                cmd.Parameters.AddWithValue("@player_z", data.playerPos.Z);
                cmd.Parameters.AddWithValue("@vel_x", data.velocity.X);
                cmd.Parameters.AddWithValue("@vel_y", data.velocity.Y);
                cmd.Parameters.AddWithValue("@vel_z", data.velocity.Z);
                cmd.Parameters.AddWithValue("@cam_near_clip", data.CamNearClip);
                cmd.Parameters.AddWithValue("@cam_far_clip", data.CamFarClip);
                cmd.Parameters.AddWithValue("@scene_id", data.sceneGuid);
                var snapshotid = (int) cmd.ExecuteScalar();
                cmd.Parameters.Clear();
                cmd.Parameters.Add("@snapshot", NpgsqlDbType.Integer);
                cmd.Parameters.AddWithValue("@type", NpgsqlDbType.Enum, DetectionType.background);
                cmd.Parameters.Add("@x", NpgsqlDbType.Real);
                cmd.Parameters.Add("@y", NpgsqlDbType.Real);
                cmd.Parameters.Add("@z", NpgsqlDbType.Real);
                cmd.Parameters.Add("@xrot", NpgsqlDbType.Real);
                cmd.Parameters.Add("@yrot", NpgsqlDbType.Real);
                cmd.Parameters.Add("@zrot", NpgsqlDbType.Real);
                cmd.Parameters.Add("@bbox", NpgsqlDbType.Box);
                cmd.Parameters.Add("@minx", NpgsqlDbType.Real);
                cmd.Parameters.Add("@miny", NpgsqlDbType.Real);
                cmd.Parameters.Add("@minz", NpgsqlDbType.Real);
                cmd.Parameters.Add("@maxx", NpgsqlDbType.Real);
                cmd.Parameters.Add("@maxy", NpgsqlDbType.Real);
                cmd.Parameters.Add("@maxz", NpgsqlDbType.Real);
                cmd.Parameters.Add("@vel_x", NpgsqlDbType.Real);
                cmd.Parameters.Add("@vel_y", NpgsqlDbType.Real);
                cmd.Parameters.Add("@vel_z", NpgsqlDbType.Real);
                cmd.Parameters.AddWithValue("@class", NpgsqlDbType.Enum, DetectionClass.Unknown);
                cmd.Parameters.Add("@handle", NpgsqlDbType.Integer);
                cmd.CommandText =
                    "INSERT INTO detections (snapshot_id, type, pos, rot, bbox, class, handle, bbox3d, velocity) VALUES " +
                    "(@snapshot, @type, ST_MakePoint(@x,@y,@z), ST_MakePoint(@xrot, @yrot, @zrot), @bbox, @class, @handle," +
                    "ST_3DMakeBox(ST_MakePoint(@minx,@miny,@minz), ST_MakePoint(@maxx, @maxy, @maxz)), ST_MakePoint(@vel_x, @vel_y, @vel_z))";
                cmd.Prepare();


                foreach (var detection in data.Detections)
                {
                    cmd.Parameters["@snapshot"].Value = snapshotid;
                    cmd.Parameters["@type"].Value = detection.Type;
                    cmd.Parameters["@x"].Value = detection.Pos.X;
                    cmd.Parameters["@y"].Value = detection.Pos.Y;
                    cmd.Parameters["@z"].Value = detection.Pos.Z;
                    cmd.Parameters["@xrot"].Value = detection.Rot.X;
                    cmd.Parameters["@yrot"].Value = detection.Rot.Y;
                    cmd.Parameters["@zrot"].Value = detection.Rot.Z;
                    cmd.Parameters["@bbox"].Value =
                        new NpgsqlBox(detection.BBox.Max.Y, detection.BBox.Max.X, detection.BBox.Min.Y,
                            detection.BBox.Min.X);
                    cmd.Parameters["@class"].Value = detection.cls;
                    cmd.Parameters["@handle"].Value = detection.Handle;
                    cmd.Parameters["@minx"].Value = detection.BBox3D.Minimum.X;
                    cmd.Parameters["@miny"].Value = detection.BBox3D.Minimum.Y;
                    cmd.Parameters["@minz"].Value = detection.BBox3D.Minimum.Z;

                    cmd.Parameters["@maxx"].Value = detection.BBox3D.Maximum.X;
                    cmd.Parameters["@maxy"].Value = detection.BBox3D.Maximum.Y;
                    cmd.Parameters["@maxz"].Value = detection.BBox3D.Maximum.Z;

                    cmd.Parameters["@vel_x"].Value = detection.velocity.X;
                    cmd.Parameters["@vel_y"].Value = detection.velocity.Y;
                    cmd.Parameters["@vel_z"].Value = detection.velocity.Z;

                    cmd.ExecuteNonQuery();
                }
            }

            trans.Commit();
            conn.Close();
        }
    }
}