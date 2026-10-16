namespace Telemetry
{
    void SendConfig(Net::Socket@ sock) {
        sock.WriteRaw(
            '{' + Text::Join({
                '"finished":"?"',
                '"ui_sequence":"I"',
                '"landmark_index":"I"',
                '"standing_landmark_index":"I"',
                '"racetime":"i"',
                '"position":["f","f","f"]',
                '"velocity":["f","f","f"]',
                '"forward":["f","f","f"]',
                '"left":["f","f","f"]',
                '"up":["f","f","f"]',
                '"steer":"f"',
                '"accelerate":"f"',
                '"brake":"?"',
                '"distance":"f"',
                '"speed":"f"',
                '"accel_coef":"f"',
                '"control_coef":"f"',
                '"gravity_coef":"f"',
                '"adherence_coef":"f"',
                '"upwardness":"f"',
                '"wheels_contact_count":"I"',
                '"wheels_skidding_count":"I"',
                '"flying_duration":"I"',
                '"skidding_duration":"I"',
                '"handicap_no_gas_duration":"I"',
                '"handicap_force_gas_duration":"I"',
                '"handicap_no_brakes_duration":"I"',
                '"handicap_no_steering_duration":"I"',
                '"handicap_no_grip_duration":"I"',
                '"reactor_boost_level":"I"',
                '"reactor_boost_type":"I"',
                '"reactor_inputs_x":"?"',
                '"is_ground_contact":"?"',
                '"is_reactor_ground_mode":"?"',
                '"is_wheels_burning":"?"',
                '"ground_dist":"f"',
                '"gear":"I"',
                '"engine_on":"?"',
                '"is_turbo":"?"',
                '"turbo_time":"f"',
                '"bullet_time_normed":"f"',
                '"simulation_time_coef":"f"',
                '"air_brake_normed":"f"',
                '"spoiler_open_normed":"f"',
                '"wings_open_normed":"f"',
                '"is_top_contact":"?"',
                '"wetness":"f"',
                '"water_immersion_coef":"f"',
                '"water_over_dist_normed":"f"',
                '"side_speed":"f"',
                '"rpm":"f"',
                '"front_speed":"f"',
                '"fl_wheel_steer_angle":"f"',
                '"fl_wheel_rotation":"f"',
                '"fl_wheel_damper_len":"f"',
                '"fl_wheel_slip_coef":"f"',
                '"fl_wheel_dirt":"f"',
                '"fl_wheel_break_coef":"f"',
                '"fl_wheel_tire_wear":"f"',
                '"fl_wheel_icing":"f"',
                '"fl_wheel_contact_material":"I"',
                '"fr_wheel_steer_angle":"f"',
                '"fr_wheel_rotation":"f"',
                '"fr_wheel_damper_len":"f"',
                '"fr_wheel_slip_coef":"f"',
                '"fr_wheel_dirt":"f"',
                '"fr_wheel_break_coef":"f"',
                '"fr_wheel_tire_wear":"f"',
                '"fr_wheel_icing":"f"',
                '"fr_wheel_contact_material":"I"',
                '"rl_wheel_steer_angle":"f"',
                '"rl_wheel_rotation":"f"',
                '"rl_wheel_damper_len":"f"',
                '"rl_wheel_slip_coef":"f"',
                '"rl_wheel_dirt":"f"',
                '"rl_wheel_break_coef":"f"',
                '"rl_wheel_tire_wear":"f"',
                '"rl_wheel_icing":"f"',
                '"rl_wheel_contact_material":"I"',
                '"rr_wheel_steer_angle":"f"',
                '"rr_wheel_rotation":"f"',
                '"rr_wheel_damper_len":"f"',
                '"rr_wheel_slip_coef":"f"',
                '"rr_wheel_dirt":"f"',
                '"rr_wheel_break_coef":"f"',
                '"rr_wheel_tire_wear":"f"',
                '"rr_wheel_icing":"f"',
                '"rr_wheel_contact_material":"I"'
            }, ',') + '}'
        );
    }

    uint8 BoolBytes(bool b) {
        return b ? 1:0;
    }

    bool SendVec3(Net::Socket@ sock, vec3&in vec) {
        sock.Write(vec.x);
        sock.Write(vec.y);
        return sock.Write(vec.z);
    }

    bool Send(Net::Socket@ sock) {
        auto cp = GetCurrentPlayground();
        if (cp is null || cp.GameTerminals.Length == 0) {
            return true;
        }
        auto terminal = cp.GameTerminals[0];
        if (terminal.ControlledPlayer is null) {
            return true;
        }
        auto vp = cast<CSmPlayer>(terminal.ControlledPlayer);
        if (vp.ScriptAPI is null) {
            return true;
        }
        auto sapi = cast<CSmScriptPlayer>(vp.ScriptAPI);
        auto vps = VehicleState::ViewingPlayerState();
        if (vps is null) {
            return true;
        }

        bool finished = (
            terminal.UISequence_Current == SGamePlaygroundUIConfig::EUISequence::EndRound
            || terminal.UISequence_Current == SGamePlaygroundUIConfig::EUISequence::Finish
        );

        sock.Write(BoolBytes(finished));
        sock.Write(uint(terminal.UISequence_Current));
        sock.Write(vp.CurrentLaunchedRespawnLandmarkIndex);
        sock.Write(vp.CurrentStoppedRespawnLandmarkIndex);
        sock.Write(GetRaceTime(sapi));
        SendVec3(sock, vps.Position);
        SendVec3(sock, vps.WorldVel);
        SendVec3(sock, vps.Dir);
        SendVec3(sock, vps.Left);
        SendVec3(sock, vps.Up);
        sock.Write(sapi.InputSteer);
        sock.Write(sapi.InputGasPedal);
        sock.Write(BoolBytes(sapi.InputIsBraking));
        sock.Write(sapi.Distance);
        sock.Write(sapi.Speed);
        sock.Write(sapi.AccelCoef);
        sock.Write(sapi.ControlCoef);
        sock.Write(sapi.GravityCoef);
        sock.Write(sapi.AdherenceCoef);
        sock.Write(sapi.Upwardness);
        sock.Write(sapi.WheelsContactCount);
        sock.Write(sapi.WheelsSkiddingCount);
        sock.Write(sapi.FlyingDuration);
        sock.Write(sapi.SkiddingDuration);
        sock.Write(sapi.HandicapNoGasDuration);
        sock.Write(sapi.HandicapForceGasDuration);
        sock.Write(sapi.HandicapNoBrakesDuration);
        sock.Write(sapi.HandicapNoSteeringDuration);
        sock.Write(sapi.HandicapNoGripDuration);
        sock.Write(uint(vps.ReactorBoostLvl));
        sock.Write(uint(vps.ReactorBoostType));
        sock.Write(BoolBytes(vps.ReactorInputsX));
        sock.Write(BoolBytes(vps.IsGroundContact));
        sock.Write(BoolBytes(vps.IsReactorGroundMode));
        sock.Write(BoolBytes(vps.IsWheelsBurning));
        sock.Write(vps.GroundDist);
        sock.Write(vps.CurGear);
        sock.Write(BoolBytes(vps.EngineOn));
        sock.Write(BoolBytes(vps.IsTurbo));
        sock.Write(vps.TurboTime);
        sock.Write(vps.BulletTimeNormed);
        sock.Write(vps.SimulationTimeCoef);
        sock.Write(vps.AirBrakeNormed);
        sock.Write(vps.SpoilerOpenNormed);
        sock.Write(vps.WingsOpenNormed);
        sock.Write(BoolBytes(vps.IsTopContact));
        sock.Write(vps.WetnessValue01);
        sock.Write(vps.WaterImmersionCoef);
        sock.Write(vps.WaterOverDistNormed);
        sock.Write(VehicleState::GetSideSpeed(vps));
        sock.Write(sapi.EngineRpm);
        sock.Write(vps.FrontSpeed);
        sock.Write(vps.FLSteerAngle);
        sock.Write(vps.FLWheelRot);
        sock.Write(vps.FLDamperLen);
        sock.Write(vps.FLSlipCoef);
        sock.Write(VehicleState::GetWheelDirt(vps, 0));
        sock.Write(vps.FLBreakNormedCoef);
        sock.Write(vps.FLTireWear01);
        sock.Write(vps.FLIcing01);
        sock.Write(uint(vps.FLGroundContactMaterial));
        sock.Write(vps.FRSteerAngle);
        sock.Write(vps.FRWheelRot);
        sock.Write(vps.FRDamperLen);
        sock.Write(vps.FRSlipCoef);
        sock.Write(VehicleState::GetWheelDirt(vps, 1));
        sock.Write(vps.FRBreakNormedCoef);
        sock.Write(vps.FRTireWear01);
        sock.Write(vps.FRIcing01);
        sock.Write(uint(vps.FRGroundContactMaterial));
        sock.Write(vps.RLSteerAngle);
        sock.Write(vps.RLWheelRot);
        sock.Write(vps.RLDamperLen);
        sock.Write(vps.RLSlipCoef);
        sock.Write(VehicleState::GetWheelDirt(vps, 2));
        sock.Write(vps.RLBreakNormedCoef);
        sock.Write(vps.RLTireWear01);
        sock.Write(vps.RLIcing01);
        sock.Write(uint(vps.RLGroundContactMaterial));
        sock.Write(vps.RRSteerAngle);
        sock.Write(vps.RRWheelRot);
        sock.Write(vps.RRDamperLen);
        sock.Write(vps.RRSlipCoef);
        sock.Write(VehicleState::GetWheelDirt(vps, 3));
        sock.Write(vps.RRBreakNormedCoef);
        sock.Write(vps.RRTireWear01);
        sock.Write(vps.RRIcing01);
        return sock.Write(uint(vps.RRGroundContactMaterial));
    }
}