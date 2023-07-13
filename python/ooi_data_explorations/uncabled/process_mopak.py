#!/usr/bin/env python
# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
import xarray as xr
from scipy.signal import buttord, butter, filtfilt, detrend, welch
from scipy.fft import fft
from scipy.signal.windows import hann
from scipy.integrate import cumulative_trapezoid
from scipy.interpolate import interp1d

# +
ATTRS = ATTRS = {
    'significant_wave_height': {
        'long_name': 'Significant Wave Height',
        'standard_name': 'sea_surface_wave_significant_height',
        'units': 'm',
        'type':'zero-crossing',
        'comment': ('Wave height is defined as the vertical distance from a wave trough to the following wave crest. '
                    'The significant wave height is the mean trough to crest distance measured during the observation '
                    'period of the highest one-third of waves. Calculated from the zero down-crossing significant wave '
                    'height.'),
    },
    'peak_wave_period': {
        'long_name': 'Peak Wave Period',
        'standard_name': 'sea_surface_wave_period_at_variance_spectral_density_maximum',
        'units': 's',
        'type': 'zero-crossing',
        'comment': ('Wave period is the interval of time between repeated features on the waveform such as crests, '
                    'troughs or upward passes through the mean level. The peak wave period, is the period of the most '
                    'energetic waves in the total wave spectrum at a specific location.'),
    },
    'mean_wave_height': {
        'long_name': 'Mean wave height',
        'standard_name': 'sea_surface_wave_mean_height',
        'units': 'm',
        'type': 'zero-crossing',
        'comment': ('Wave height is defined as the vertical distance from a wave trough to the following wave crest. '
                    'The mean wave height is the mean trough to crest distance measured during the observation period. '
                    'This is calculated from the average zero down-crossing wave height'),
    },
    'mean_wave_period': {
        'long_name': 'Mean Wave Period',
        'standard_name': 'sea_surface_wave_mean_period',
        'units': 's',
        'type': 'zero-crossing',
        'comment': ('Wave period is the interval of time between repeated features on the waveform such as crests, '
                    'troughs or upward passes through the mean level. Wave mean period is the mean period measured '
                    'over the observation duration. Calculated as the average zero down-crossing wave period. '),
    },
    'peak_wave_direction': {
        'long_name': 'Peak Wave Direction',
        'standard_name': 'sea_surface_wave_from_direction_at_variance_spectral_density_maximum',
        'units': 'degrees',
        'type': 'directional',
        'comment': ('Peak wave direction is the direction from which the most energetic waves are coming. The '
                    'spectral peak is the most energetic wave in the total wave spectrum. The direction is a '
                    'bearing in the usual geographical sense, measured positive clockwise from due north. This '
                    'parameter is derived via the PUV-method.'),
    },
    'peak_wave_spread': {
        'long name': 'Peak Wave Spread',
        'standard_name': 'sea_surface_wave_from_direction_at_variance_spectral_density_maximum',
        'units': 'degrees',
        'type': 'directional',
        'comment': ('Peak wave spread is the directional spread of the most energetic waves in the total wave '
                    'spectrum. Directional spread is the (one-sided) directional width within a given sub-domain '
                    'of the wave directional spectrum. This parameter is derived via the PUV-method.'),
    },
    'peak_wave_period_puv': {
        'long_name': 'Peak Wave Period',
        'standard_name': 'sea_surface_wave_period_at_variance_spectral_density_maximum',
        'units': 's',
        'type': 'directional',
        'comment': ('Wave period is the interval of time between repeated features on the waveform such as crests, '
                    'troughs or upward passes through the mean level. The peak wave period, is the period of the most '
                    'energetic waves in the total wave spectrum at a specific location. This parameter is derived '
                    'via the PUV-method and by parabolic fitting of the log-averaged frequency bands.'),
    },
    'wave_height_hm0': {
        'long_name': 'Significant Wave Height from Spectral Moment 0',
        'standard_name': 'sea_surface_wave_significant_height_from_variance_spectral_density',
        'units': 'm',
        "type": 'directional',
        'comment': ('Wave height is defined as the vertical distance from a wave trough to the following '
                    'wave crest. The significant wave height (hm0) is the mean wave height of the highest '
                    'one-third of waves as estimated from the zeroth-spectral moment m0, where '
                    'hm0 = 4*sqrt(m0), and m0 is the intregral of the S(f)*df with f = F1 to F2 in Hz. This '
                    'parameter is derived via the PUV-method.'),
    },
    'time': {
        'long_name': 'time',
        'standard_name': 'time',
        'comment': ('The time given here is the start time of the sample collection. Sample collection continues '
                    'for 20 minutes at 1 Hz')
    },
    'deployment': {
        'long_name': 'Deployment Number',
        'comment': ('The deployment number of the instrument.')
    }
}


def filter_coefficients(fs, fc, ludo=True):
    """
    High-pass filter which retains real acceleration but removes drift
    
    The filter was coshen so that the spectra of the doubly integrated
    acceleration matched the frequency domain integrated power spectrum
    in the pass band. The comparison is most sensitive to the transition
    width.
    
    The selected transition region to lie in the overlap region between 
    the integrated angle rate and the accelerometer based angle estimates.
    The fileter is shift to higher frequencies by 1/4 to 1/2 decade.
    
    NOTE: The scipy buttord function optimizes for the stopband, whereas
    MatLab Buttord optimizes for the passband, resulting in a -3 dB shift
    
    Parameters
    ----------
    fs: float, int
        Sampling frequency
    fc: float, int
        
    Returns
    -------
    """
    n_freq = fs/2
    wp = fc/n_freq
    if ludo:
        ws = 0.8*wp
        n, wn = buttord(wp, ws, 3, 7)
    else:
        ws = 0.7*wp
        n, wn = buttord(wp, ws, 10, 25)
        
    b_high, a_high = butter(n, wn, "high")
    
    return b_high, a_high


def identify_samples(ds, threshold):
    """
    Defines sample intervals for burst/pulse sampling instruments.
    
    Parameters
    ----------
    ds: xarray.Dataset, xarray.DataArray
        An xarray dataset or dataarray with time as the primary dimension
    threshold: int
        The threshold in seconds that separates burst sample intervals
        
    Returns
    -------
    sample: array_like
        A numpy array the length of the input time dimension with the 
        sample interval number
    """
    # First, get the difference of the time in seconds
    dt = ds["time"].diff(dim="time").dt.seconds
    
    # Next, find where the gaps in the time series occur
    ends = np.where(dt > threshold)[0]
    
    # increase index of ends by 1 since diff drops the first entry, and python is left index inclusive,
    # right index exclusive
    ends = ends + 1
    
    # Find the sampling groups
    sample = np.zeros(ds.time.shape, dtype=int)
    for i, end in enumerate(ends):
        if i == 0:
            start = 0
        elif end == ends[-1]:
            start = ends[i-1]
            end = len(sample)+1
        else:
            start = ends[i-1]
        sample[start:end] = i
        
    return sample


def wave_statistics(heave, fs, npt):
    """
    Calculate the wave statistics from the wave time series
    
    Parameters
    ----------
    heave: array_like
        An array of vertical displacement (heave)
    fs: float
        Sampling frequency
    npt: int
        Number of points in the fft
        
    Returns
    -------
    Hsig: float
        Signficant wave height
    Havg: float
        Average wave height
    Tsig: float
        Significant wave period
    Tavg: float
        Average wave period
    
    """
    # Detrend the heave and calculate the significant and average wave height
    heave = detrend(heave)
    Hsig = 4*np.std(heave)
    Havg = np.mean(heave)
    
    bw = np.ones(5)/5
    aw = 1
    
    # Calculate the significant and average wave period
    if Hsig > 0.2:
        [fr, wxx] = welch(heave, fs, window=hann(npt), nfft=npt, noverlap=0, detrend=False)
        wxx[0] = wxx[1]
        wxxf = filtfilt(bw, aw, wxx)
        i = np.where(fr<0.01)[0]
        wxxf[i] = 1E-7
        i = np.where(wxxf == np.max(wxxf))[0]
        fr1 = np.mean(fr[i])
        Tsig = 1/fr1
        Tavg = zero_crossings(heave, fs)
    else:
        Tsig = np.nan
        Tavg = np.nan
        
    return Hsig, Havg, Tsig, Tavg


def zero_crossings(heave, fs, detrend=False):
    """
    Compute average wave period using the zero-crossing method
    
    Parameters
    ----------
    heave: array_like
        The heave (z-displacement) of the 
    fs: float
        The sampling frequency
    detrend: boolean, Default = False
        Boolean indicating whether or not to detrend the heave
        values before calculating the zero crossings
        
    Returns
    -------
    tm: float
        The calculated average wave period
    """
    
    n=len(heave)
    T=(n-1)/fs
    heave = heave-np.mean(heave)
    sheave = np.sign(heave)
    sw1 = sheave[0:len(heave)-1]
    sw2 = sheave[1:len(heave)]
    i = np.where(sw1 != sw2)[0]
    fm = len(i)/2/T
    tm = 1/fm
    return tm


def updater(IN, ANGLES):
    """
    Computes the angular update matrix described in Edson et al (1998) and Thwaites (1995)
    
    Parameters
    ----------
    IN: array_like
        A (3 x n) matrix of the angular rates
    ANGLES: array_like
        A (3 x n) matrix of the euler angles phi, theta, psi, where:
            phi = angles[0,:] - rotation of x'y'z' about x axis (roll)
            theta = angles[1,:] - rotation of x'y'z' about y axis (pitch)
            psi = angles[2,:] - rotations of x'y'z' about z axis (yaw)
            
    Returns
    -------
    OUT: array_like
        A (3 x n) matrix of the updated angular rates
    """
    
    p = ANGLES[0,:]
    t = ANGLES[1,:]
    ps = ANGLES[2,:]
    
    up = IN[0,:]
    vp = IN[1,:]
    wp = IN[2,:]
    
    u = up + vp*np.sin(p)*np.tan(t) + wp*np.cos(p)*np.tan(t)
    v = 0  + vp*np.cos(p)           - wp*np.sin(p)
    w = 0  + vp*np.sin(p)/np.cos(t) + wp*np.cos(p)/np.cos(t)
    
    return np.vstack([u, v, w])


def euler_angles(ahi, bhi, fs, accm, ratem, gyro, gravity, iters=5):
    """
    Derive the euler angles from the accelerometers and rate sensors.
    
    The equation for the derivation of the euler angles are:
        angle = slow_angle (from accelerometers) + fast_angle (integrated rate sensors)
        
    Parameters
    ----------
    ahi: array_like
        The filter coefficients a
    bhi: array_like
        The filter coefficients b
    fs: float
        The sample frequency
    accm: array_like
        A (3 x n) array of recalibrated linear accelerations in (x, y, z)
    ratem: array_like
        A (3 x n) array of recalibrated angular rates in (x, y, z)
    gyro: array)like
        A (1 x n) array of the gyro signal
    gravity: float
        The gravitational constant
    iters: int, Default = 5
        Number of iterations to filter
    
    Returns
    -------
    euler: array_like
        A (3 x n) array of the euler angles (phi, theta, psi) in radians
    dr: array_like
        A (3 x n) array of detrended angular rates in (x, y, z)
    """
    # Unwrap the compass data
    gyro = np.unwrap(gyro)
    
    # Remove the mean from the rate sensors
    ratem = detrend(ratem)
    
    # ==================================================================
    # Low frequency angles from accelerometers and gyro
    # Slow roll from gravity effects on horizontal accelerations
    # Low pass filter since high frequency horizontal accelerations may be real
    
    # PITCH
    # Use small angles
    theta_th = np.minimum(-accm[0, :] / gravity, 1)
    theta = theta_th
    
    # Remove freefall values
    ind = np.where(np.abs(accm[0, :]) < gravity)
    theta[ind] = np.arcsin(-accm[0, ind] / gravity) 
    
    # Calculate the slow angles
    theta_slow = theta - filtfilt(bhi, ahi, theta)
    
    # ROLL
    # Use small angles
    phi_th = accm[1] / gravity
    phi = phi_th
    
    # Find well-behaved angles
    ind = np.where(np.abs(accm[1] / gravity / np.cos(theta_slow)) < 1)[0]
    phi[ind] = np.arcsin(accm[1, ind] / gravity / np.cos(theta_slow[ind]))
    
    # Filter the roll angles
    phi_slow = phi - filtfilt(bhi, ahi, phi)
    
    # YAW
    psi_slow = gyro[0] - filtfilt(bhi,ahi,gyro[0]);
    
    # ==================================================================
    # EULER ANGLES
    # Calculate the euler angles, starting with the slow angles as first guess
    euler = np.vstack([phi_slow, theta_slow, psi_slow])
    rates = updater(ratem, euler)
    
    # Recalculate the euler angles by adding the integrated rates to the
    # slow angles, updating the euler angles, and repeating for iters
    for i in np.arange(0, iters):
        phi = phi_slow + filtfilt(bhi, ahi, 1/fs*cumulative_trapezoid(rates[0, :], initial=0))
        theta = theta_slow + filtfilt(bhi, ahi, 1/fs*cumulative_trapezoid(rates[1, :], initial=0))
        psi = psi_slow + filtfilt(bhi, ahi, 1/fs*cumulative_trapezoid(rates[2, :], initial=0))
        euler = np.vstack([phi, theta, psi])
        rates = updater(ratem, euler)
        rates[0] = detrend(rates[0], type='constant')
        rates[1] = detrend(rates[1], type='constant')
        rates[2] = detrend(rates[2], type='constant')
        
    return euler, ratem


def rotate(IN, ANGLES, IFLAG=0):
    """
    Rotate a vector from one cartesian basis to another based on Euler angles.
    
    This function rotates a vector from one cartesian basis to another based on
    the associated Euler angles, defined as rotations around the reference axes
    (x,y,z). The axis in the rotated frame are (x',y',z').
    
    Parameters
    ----------
    IN: array_like
        A (3 x n) matrix of the input vector components
    ANGLES: array_like
        A (3 x n) matrix of the euler angles phi, theta, psi, where:
            phi = angles[0,:] - rotation of x'y'z' about x axis (roll)
            theta = angles[1,:] - rotation of x'y'z' about y axis (pitch)
            psi = angles[2,:] - rotations of x'y'z' about z axis (yaw)
    IFLAG: int, Default = 0
        For rotation of measurements from body coordinates to earth coordinates
        the flag is set to FALSE. This is a 321 rotation, where the first rotation
        is around the 3-axis (z-axis, angle psi), the second rotation is then
        about the intermediate 2 axis (y-axis, angle theta), and the third rotation
        is about the intermediate 1 axis (x-axis, angle phi)
        
        An integer value indicates which direction the rotation is in:
            0: "IN" vector transformed from x'y'z' -> xyz
            1: "IN" vector transformed from xyz -> x'y'z'
            
    Returns
    -------
    OUT: array_like
        A (3 x n) matrix of the rotated input vector components
    """
    
    # Grab the Euler angles
    phi = ANGLES[0,:]
    theta = ANGLES[1,:]
    psi = ANGLES[2,:]
    
    # Get the input vector components
    up = IN[0,:]
    vp = IN[1,:]
    wp = IN[2,:]
    
    # Perform rotation
    # If True: xyz -> x'y'z'
    if IFLAG == 1:
        u = up * np.cos(theta) * np.cos(psi) + vp * np.cos(theta)*np.sin(psi) - wp * np.sin(theta)
        v = up * (np.sin(phi) * np.sin(theta) * np.cos(psi) - np.cos(phi) * np.sin(psi)) + vp * (np.sin(phi) * np.sin(theta) * np.sin(psi) + np.cos(phi) * np.cos(psi)) + wp * (np.cos(theta) * np.sin(phi))
        w = up * (np.cos(phi) * np.sin(theta) * np.cos(psi) + np.sin(phi) * np.sin(psi)) + vp * (np.cos(phi) * np.sin(theta) * np.sin(psi) - np.sin(phi) * np.cos(psi)) + wp * (np.cos(theta) * np.cos(phi))
    # If False: x'y'z' -> xyz
    else:
        u = up * np.cos(theta) * np.cos(psi) + vp * (np.sin(phi) * np.sin(theta) * np.cos(psi) - np.cos(phi) * np.sin(psi)) + wp * (np.cos(phi) * np.sin(theta) * np.cos(psi) + np.sin(phi) * np.sin(psi))
        v = up * np.cos(theta) * np.sin(psi) + vp * (np.sin(phi) * np.sin(theta) * np.sin(psi) + np.cos(phi) * np.cos(psi)) + wp * (np.cos(phi) * np.sin(theta) * np.sin(psi) - np.sin(phi) * np.cos(psi))
        w = up * (-np.sin(theta)) + vp * (np.cos(theta) * np.sin(phi)) + wp * (np.cos(theta) * np.cos(phi));
        
    # Return the rotated vector
    OUT = np.vstack((u, v, w))
    return OUT


def heave(omegam, euler, accm, fs, bhi, ahi, R, gravity):
    """
    Correct sonic anemometer components for platform motion and orientation
    
    Parameters
    ----------
    omegam: array_like
        A (3 x n) measured angular rate vector in the platform frame
    euler: array_like
        A (3 x n) array of euler angles (phi, theta, psi)
    accm: array_like
        A (3 x n) array of platform accelerations
    R: array_like
        Vector distance from motion pack to wave sensor
        
    Returns
    -------
    uvw_plat: array_like
        The platform velocity at sensor location
    xyz_plat: array_like
        The platform displacement at sensor location
    """
    n, m = omegam.shape
    Rvec = np.vstack([R[0]*np.ones(m), R[1]*np.ones(m), R[2]*np.ones(m)])
    uvw_rot = np.cross(omegam, Rvec, axis=0)
    uvw_rot = rotate(uvw_rot, euler, 0)
    
    # Rotate the accelerometer and remove gravity
    acc = rotate(accm, euler, 0)
    acc[2, :] = acc[2, :] - gravity
    
    motion = np.ones(acc.shape)
    uvw_plat = np.ones(acc.shape)
    for i in range(0, 3):
        acc[i, :] = filtfilt(bhi, ahi, acc[i, :])
        motion[i, :] = cumulative_trapezoid(acc[i, :], initial=0) / fs + uvw_rot[i, :]
        uvw_plat[i, :] = filtfilt(bhi, ahi, motion[i, :])
    
    # Integrate again to get the displacements
    xyz_plat = np.ones(uvw_plat.shape)
    for i in range(0, 3):
        xyz_plat[i, :] = cumulative_trapezoid(uvw_plat[i, :], initial=0) / fs
        xyz_plat[i, :] = filtfilt(bhi, ahi, xyz_plat[i, :])
        
    return uvw_plat, xyz_plat


def uvw_xyz(gyro, platform, angular_rates, fs, f_cutoff=1/30, com_offset=[0, 0, 0.5], G=9.8):
    """
    Calculate the displacements and velocities from accelerometer data
    
    Parameters
    ----------
    gyro: array_like
        An array of the processed and cleaned compass directions
        measured by the MOPAK
    platform: array_like
        A (3 x n) array of the processed and cleaned mopak accelerations in
        the (x, y, z) directions
    angular_rates: array_like
        A (3 x n) array of the processed and cleaned angular rates measured
        by the MOPAK
    fs: float
        The sampling frequency
    f_cutoff: float, Default=1/30
        The cutoff period for waves
    com_offset: list[x, y, z], Default=[0, 0, 0.5]
        A list of the offsets from the center of mass of the MOPAK (m)
    G: float, Default = 9.8
        Gravity
        
    Returns
    -------
    uvw: array_like
        A (3 x n) array of platform velocities in the (u, v, w) directions
        based at sensor location
    xyz: array_like
        A (3 x n) array of platform displacements in the (x, y, z) directions
        at sensor location
    """
    # 30 second cutoff period for waves
    bhiwaves, ahiwaves = filter_coefficients(fs, f_cutoff)
    
    #  despike the data
    platform, bad_platform = despike(platform)
    ang_rate, bad_ang_rate = despike(angular_rates)

    # Calculate the compass offset angles
    gx = np.cos(gyro)
    gy = np.sin(gyro)

    # Remove spikes from the compass offset angles
    [gx, bad_gx] = despike(gx)
    [gy, bad_gy] = despike(gy)

    # Smooth the compass angles
    g_smooth = np.arctan2(gy, gx)
    gyro = g_smooth

    # Calculate the Euler angles, velocities, and displacements
    euler, dr = euler_angles(ahiwaves, bhiwaves, fs, platform, ang_rate, gyro, G)
    uvw, xyz = heave(dr, euler, platform, fs, bhiwaves, ahiwaves, com_offset, G)
    
    return uvw, xyz


def despike(data, n_std=4, iters=3):
    """
    Despike MOPAK data
    
    Parameters
    ----------
    data: array_like
        An array containing the x, y, z accelerations as rows
    n_std: int (default = 4)
        Number of standard deviations from the median which defines
        a spike
    iters: int (default = 3)
        The number of iterations (passes) over the data to make in
        order to identify and remove spikes
        
    Returns
    -------
    """
    # Coerce entries to be at least 2d
    data = np.atleast_2d(data)
    
    # Get the median and standard deviations
    rows, n = data.shape
    t = np.arange(n)
    bad = []
    # Iterate over each row of the column separately
    for row in np.arange(rows):
        # Run three iterations to remove all possible spikes
        for i in np.arange(iters):
            # Calculate the median and standard deviations
            median = np.nanmedian(data[row, :])
            std = np.nanstd(data[row, :])
            
            # Find where the data is out-of-range
            good = np.where((data[row,:] < median+n_std*std) & (data[row, :] > median-n_std*std) & (~np.isnan(data[row, :])))[0]
            if i == 0:
                n_bad = n - len(good)
            if len(good) > 0:
                # Now use the good data points to linearly interpolate to fill in the bad data points
                ft = interp1d(t[good], data[row, good], kind="nearest", fill_value="extrapolate")
                data[row, :] = ft(t)
                
        # Save the total number of bad points
        bad.append(n_bad)
    
    return data, bad


def arctan3(y, x):
    """
    Four quadrant inverse tanges of the real elements of (y, x).
    0 <= np.atan2(y, x) <= 2*pi
    """
    theta = np.arctan2(y, x)
    theta = np.atleast_1d(theta)
    index = np.where(theta < 0)[0]
    if len(index) > 0:
        theta[index] = theta[index] + 2*np.pi
    
    return theta


def log_avg(f, s, n):
    """
    Logarithmically average the input spectrum s over frequencies f into n uniform bands.
    
    Parameters
    ----------
    f: array_like
        Frequencies f associated with the input spectrum
    s: array_like
        Input spectrum defined over frequencies f
    n: int
        Number of uniformally-spaced log10 frequencies bands over which
        the spectrum is averaged
        
    Returns
    -------
    F: array_like
        The array of averaged bandwidth-centered frequencies
    S: array_like
        The averaged spectrum
    dF: array_like
        The bandwidths of each frequency-band
    Ns: array_like
        The start indices of each frequency band
    Ne: array_like
        The end indices of each frequency band
    """
    
    lf = np.log(f)
    
    # Log frequency increment
    dlf = 1.000000001*(lf[len(f)-1] - lf[0]) / n
    
    # Get the array of transitions plus the final frequency
    NDX = 1 + np.floor((lf - lf[0]) / dlf)
    AA = np.where(np.diff(NDX) > 0)[0]
    AA = np.concatenate([AA, np.ones(1)*(len(f)-1)]).astype(int)

    # Calculate the averaged spectrum and frequencies
    Cs = np.cumsum(s)
    Cf = np.cumsum(f)
    F = np.concatenate([np.array([Cf[AA[0]]]), np.diff(Cf[AA])]) / np.concatenate([np.array([AA[0]+1]), np.diff(AA)])
    S = np.concatenate([np.array([Cs[AA[0]]]), np.diff(Cs[AA])]) / np.concatenate([np.array([AA[0]+1]), np.diff(AA)])

    # Calculate the frequency bandwidths
    dF = np.concatenate([np.array([AA[0]+1]), np.diff(AA)]) * (f[9]-f[8])

    # Get the start and end indices of each band
    Ns = np.concatenate([np.array([0]), AA[0:-1]+1])
    Ne = AA
    
    return F, S, dF, Ns, Ne


def wave_spectra(u, v, p, dt, nF, hp, hv, params=[0.03, 200, 0.1, 0]):
    """
    Calculate the wave direction and spreading using the Nortek PUV-method
    
    Parameters
    ----------
    u: array_like
        East components of velocity (m/s)
    v: array_like
        North component of velocity (m/s)
    p: array_like
        Pressure (m)
    dt: float
        Sample interval (sec) (typically 0.5 or 1 sec)
    nF: arrayl_like
        Nominal number of output frequencies
    hp: float
        height of the pressure sensor above the bottom (m)
        which is the water depth is the mean pressure + hp)
    hv: float
        height of the velocity cell above the pressure sensor (m)
    params: list[lf_cutoff, max_fac, min_spec, n_dir]
        lf_cutoff: float, Default=0.03
            Low frequency cutoff where F < lf are not outputted
        max_fac: float, Default=200
            Largest factor scaping pressure to surface elevation
            Spectra and directions at F > max_fac are NaNs
        min_spec: float, Default= 0.03
            Minimum spectral level for which direction is computed
            Directions for spectra < minspec are returned NaNs
        n_dir: float, Default=0
            Direction of the "north" component (degrees)
    
    Returns
    -------
    u_spectra:
        Surface elevation spectra (m**2/Hz) based on velocity data
    p_spectra:
        Surface elevation spectra (m**2/Hz) based on pressure data
    Tdir:
        Mean wave direction (degree)
    Ts:
        Wave spreading (deg) in an array size [nf, nt] where
        nf is the number of output frequency bands 
        nt is the number of input time series
    F:
        Center frequency of each band
    dF:
        Bandwidth of each band
    dof:
        Degrees of freedom for each band
        """
    
    # Parse out the wave parameters
    lf_cutoff = params[0]
    max_fac = params[1]
    min_spec = params[2]
    n_dir = params[3]
    
    # Number of points in time series
    n = len(p)
    
    # If the length of the time series is odd, make it even
    if n % 2 == 1:
        u = u[:-1]
        v = v[:-1]
        p = p[:-1]
        n = len(p)
    Dt = n*dt
    
    # Frequency array up to the Nyquist frequency
    f = np.arange(1, (n+1)/2) / Dt
    
    # Compute the spectrum from velocity and pressure
    u_fft = fft(u)
    v_fft = fft(v)
    p_fft = fft(p)
    
    # Compute power spectrum and ignore zero frequency
    u_power = abs(u_fft[1:int((n/2)+1)]**2)
    v_power = abs(v_fft[1:int((n/2)+1)]**2)
    p_power = abs(p_fft[1:int((n/2)+1)]**2)
    
    # Scale power spectrum
    u_power = (u_power*2)/(n**2)/f[0]
    v_power = (v_power*2)/(n**2)/f[0]
    p_power = (p_power*2)/(n**2)/f[0]

    # Scale the cross-spectra and limit frequencies
    pu_power = np.real((p_fft*np.conj(u_fft)) * 2 / (n**2) / f[0])
    pu_power = pu_power[1:int((n/2)+1)]
    pv_power = np.real((p_fft*np.conj(v_fft)) * 2 / (n**2) / f[0])
    pv_power = pv_power[1:int((n/2)+1)]
    uv_power = np.real((u_fft*np.conj(v_fft)) * 2 / (n**2) / f[0])
    uv_power = uv_power[1:int((n/2)+1)]
    
    # Average the power spectrums into log bands
    F, Cuu, _, _, _ = log_avg(f, u_power, nF)
    F, Cvv, _, _, _ = log_avg(f, v_power, nF)
    F, Cpp, _, _, _ = log_avg(f, p_power, nF)
    F, Cpu, _, _, _ = log_avg(f, pu_power, nF)
    F, Cpv, dF, Ns, Ne = log_avg(f, pv_power, nF)
    F, Cuv, _, _, _ = log_avg(f, uv_power, nF)
    dof = 2*(Ne-Ns+1)
    
    # Find low-frequency cutoff
    aa = np.where(F > lf_cutoff)[0]
    lF = len(aa)

    # Filter the frequencies
    F = F[aa]
    dF = dF[aa]
    dof = dof[aa]
    
    # Filter the cross spectrums
    Cuu = Cuu[aa]
    Cvv = Cvv[aa]
    Cpp = Cpp[aa]
    Cpu = Cpu[aa]
    Cpv = Cpv[aa]
    Cuv = Cuv[aa]
    
    # Calculate the spectra
    u_spectra = (Cuu + Cvv)
    p_spectra = Cpp
    
    # Calculate the wave direction and spreading
    Tdir = 57.296*arctan3(Cpu, Cpv)
    R2 = ((Cuu - Cvv)**2 + 4*Cuv**2)**0.5 / (Cuu+Cvv)
    Ts = 57.296* ((1-R2) / 2)**0.5
    
    # Filter the direction and spreads for values below
    # the minimum spectral levels
    ad = np.where(p_spectra < min_spec)[0]
    Tdir[ad] = np.nan
    Ts[ad] = np.nan
    
    return u_spectra, p_spectra, Tdir, Ts, F, dF, dof


def wave_spectra_statistics(u_spectra, p_spectra, Tdir, Ts, F, dF):
    """
    Calculate the wave statistics from the wave spectra using the Nortek PUV-method.
    
    Parameters
    -------
    u_spectra: array_like
        The surface elevation spectra (m**2/hz) based on velocity data
    p_spectra: array_like
        The surface elevation spectra (m**2/hz) based on pressure data
    Tdir: array_like
        The wave direction (deg)
    Ts: array_like
        The wave spreading (deg)
    F: array_like
        The center frequency of each band
    dF: array_like
        The bandwidth of each frequency band
        
    Returns
    -------
    Hm0: float
        The significant wave height
    Fs: float
        The peak frequency
    Tdir: float
        Wave direction at the peak frequency
    Ts:
        Wave spreading at the peak frequency
    """
    # Calculate the significant wave height
    Hm0 = np.max(np.cumsum(p_spectra * dF))**0.5 * 4

    # Find the peak spectra from the pressure
    B = np.max(p_spectra)
    nP = np.where(p_spectra == B)[0]
    
    A = p_spectra[nP-1][0]
    C = p_spectra[nP+1][0]
    
    # Calculate the peak frequency by interpolating using a parabolic fit
    Fs = (np.log(F[nP+1]) - np.log(F[nP-1])) * (-(C - A) / (2*(A - 2*B + C))) / 2
    Fs = np.exp(np.log(F[nP]) + Fs)[0]
    
    # Idnntify the peak direction and spread
    Tdir = Tdir[nP][0]
    Ts = Ts[nP][0]
    
    return Hm0, Fs, Tdir, Ts


def magnetometer(data):
    """
    Process and clean the magnetometer data to get compass directions
    
    This function grabs the xyz magnetomer data, gets the headings,
    corrects for the orientation of z-positive downwards, adjusts for
    the magnetic to true north misalignment, and calculates the compass
    headings (in radians)
    
    Parameters
    ----------
    data: xarray.DataSet
        An xarray dataset object containing the MOPAK data
        
    Returns
    -------
    compass: array_like 
        An array of the calculated compass directions (radians)
    """
    # ----------------------------------------------------
    # First, grab the xyz magnetometer data
    magx = data.mopak_magx.values
    magy = data.mopak_magy.values
    magz = data.mopak_magz.values
    
    # Put the data into a matrix
    magnet = np.vstack([magx, magy, magz])
    
    # ----------------------------------------------------
    # Get headings and account for z is positive downwards
    # Account for magnetic to true north misalignment
    dev = -10*np.pi/180
    magnet[0] = magnet[0]
    magnet[1] = -1*magnet[1]
    magnet[2] = -1*magnet[2]
    
    # Calculate the compass directions in radians
    compass = np.arctan2(magnet[1], magnet[0]) + dev

    # Correct for values that fall outside real ranges
    mask = compass > np.pi
    compass[mask] = compass[mask] - np.pi
    mask = compass < -1*np.pi
    compass[mask] = compass[mask] + np.pi

    # Reorient to account for z-direction
    compass = -1*compass
    
    return compass


def accelerations(data):
    """
    Process and clean the xyz accelerations
    
    This function get the MOPAK accelerations in the x, y, z
    directions (in units of g-force), corrects for the
    orientation of z-positive downwards, and derives the local
    free-fall values.
    
    Parameters
    ----------
    data: xarray.DataSet
        An xarray dataset object containing the MOPAK data downloaded
        from OOINet
    
    Returns
    -------
    platform: array_like
        A (3 x n) array of the mopak accelerations
        in the x, y, z directions in units of m/s^2
    gravity: np.float
        The local free-fall estimate
    """
    # Gravity
    G = 9.8

    # Mopak accelerations (in g-force units)
    ax = data.mopak_accelx.values
    ay = data.mopak_accely.values
    az = data.mopak_accelz.values

    # Put the accelerations into a (3 x n) array
    platform = np.vstack([ax, ay, az])
    
    # Reorient y & z positions (z is positive down)
    platform[0] = platform[0]
    platform[1] = -1*platform[1]
    platform[2] = -1*platform[2]
    
    # Calculate the local gravity values
    gravxyz = np.mean(platform.transpose(), axis=0)
    gravity = np.sqrt(np.sum(gravxyz**2))
    
    # Adjust the accelerations to be in m/s^2
    platform = platform*G
    
    return platform, gravity

    
def angular_rates(data):
    """
    Process and clean the angular rates
    
    This function get the MOPAK angular rates in the x, y, z
    directions and corrects for the orientation of z-positive 
    downwards.
    
    Parameters
    ----------
    data: xarray.DataSet
        An xarray dataset object containing the MOPAK data
    
    Returns
    -------
    angular_rates: array_like
        A (3 x n) array of the mopak angular rates
    """
    # Get the xyz angular rates
    dx = data.mopak_ang_ratex.values
    dy = data.mopak_ang_ratey.values
    dz = data.mopak_ang_ratez.values

    # Put into a matrix
    angular_rate = np.vstack([dx, dy, dz])
    
    # Reorient the y and z positions (right-hand-rule)
    angular_rate[0] = angular_rate[0]
    angular_rate[1] = -1*angular_rate[1]
    angular_rate[2] = -1*angular_rate[2]
    
    return angular_rate


def build_dataset(data, significant_wave_height, peak_wave_period, mean_wave_height, mean_wave_period,
                  peak_wave_direction_puv, peak_wave_spread_puv, peak_wave_period_puv, wave_height_hm0,
                  sample_start_time, deployment):
    """
    Takes in the calculated wave statistics are builds an xarray dataset
    
    Parameters
    ----------
    significant_wave_height: array_like
        The significant wave height (Hsig) calculated using the zero-crossing
        method (units: m)
    peak_wave_period: array_like
        The peak wave period calculated using the zero-crossing data (units: s)
    mean_wave_height: array_like
        The mean wave height calculated from the zero-crossing data (units: m)
    mean_wave_period: array_like
        The mean wave period calculated from the zero-crossing data (units: s)
    peak_wave_direction_puv: array_like
        The peak wave direction calculated using the Nortek PUV-method (units: degrees)
    peak_wave_spread_puv: array_like
        The wave spread of the peak wave calculated using the Nortek PUV-method
        (units: degrees)
    peak_wave_period_puv: array_like
        The peak wave period calculated using the Nortek PUV-method and a 
        parabolic fit across the peak frequency band (units: s)
    wave_height_hm0: array_like
        The significant wave height calculated using the Nortek PUV-method
        (units: m)
    sample_start_time: array_like
        Either an array of datetime strings or datetime objects that correspond
        to the start of each sampling period
    deployment: int, float, str
        The deployment number of the dataset being processed
        
    Returns
    -------
    ds: xarray.Dataset
        An xarray dataset which contains the wave statistics data, indexed via the
        sample_start_time, with associated metadata    
    """
    # Check that the data is all 1-d arrays
    significant_wave_height = np.atleast_1d(significant_wave_height)
    peak_wave_period = np.atleast_1d(peak_wave_period)
    mean_wave_height = np.atleast_1d(mean_wave_height)
    mean_wave_period = np.atleast_1d(mean_wave_period)
    peak_wave_direction_puv = np.atleast_1d(peak_wave_direction_puv)
    peak_wave_spread_puv = np.atleast_1d(peak_wave_spread_puv)
    peak_wave_period_puv = np.atleast_1d(peak_wave_period_puv)
    wave_height_hm0 = np.atleast_1d(wave_height_hm0)
    sample_start_time = np.atleast_1d(sample_start_time)
    
    # Check that the sample_start_times are datetime objects
    sample_start_time = sample_start_time.astype("datetime64[ns]")
    
    # Build an array of the deployment number
    deployment = np.ones(sample_start_time.shape)*int(deployment)
    deployment = deployment.astype("int")
    
    # Create a dictionary object of the data variables
    data_vars = dict(
        significant_wave_height=(["time"], significant_wave_height),
        peak_wave_period=(["time"], peak_wave_period),
        mean_wave_height=(["time"], mean_wave_height),
        mean_wave_period=(["time"], mean_wave_period),
        peak_wave_direction=(["time"], peak_wave_direction_puv),
        peak_wave_spread=(["time"], peak_wave_spread_puv),
        peak_wave_period_puv=(["time"], peak_wave_period_puv),
        wave_height_hm0 = (["time"], wave_height_hm0),
        deployment = (["time"], deployment), )
        #time=(["time"], sample_start_time)
        
    coords = dict(
        time=sample_start_time
        )
       
    # Build the dataset
    ds = xr.Dataset(
        data_vars=data_vars,
        coords=coords,
        attrs={
            "comment": ('This dataset includes the directional and non-directional '
                        'wave statistics. The non-directional wave statistics are '
                        'derived from the zero-crossing data. The directional wave '
                        'data are calculated using the PUV-technique (Pressue, '
                        'U-velocity, V-velocity) as outlined by Nortek.'),
            "id": "-".join(data.attrs["id"].split("-")[0:4]),
            "lat": data.attrs["lat"],
            "lon": data.attrs["lon"]
        }
    )
            
    # Add the variable attributes
    for var in ds.variables:
        ds[var].attrs = ATTRS[var]
    
    return ds


def calculate_wave_statistics(ds, n_std, fs, com_offset, f_cutoff, lf_cutoff, max_fac, min_spec, n_dir):
    """
    Calculate the directional and non-directional wave statistics and return a new dataset.
    
    This function takes in a dataset from the 3-axis motion pack (MOPAK) and processes it
    to derive the directional and non-directional wave statistics. The results are 
    """
      
    # --------------------------------------------------------------------
    # First, identify each wave sample
    sample = identify_samples(ds, 2400)
    
    # Add the sample as a new variable to the dataset
    ds["sample"] = (("time"), sample)
    
    # --------------------------------------------------------------------
    # Grab the constants and parameters
    G = 9.8 # Gravity
    params = [lf_cutoff, max_fac, min_spec, n_dir]
       
    # --------------------------------------------------------------------
    # Process and return the magnetic directions, platforms accelerations,
    # and angular rates from the MOPAK data
    Compass = magnetometer(ds)
    Platform, gravity = accelerations(ds)
    Deg_rate = angular_rates(ds)
    
    # --------------------------------------------------------------------
    # Calculate the wave statistics by iterating through each wave sample
    # (Note: can probably speed this portion up using Dask)
    significant_wave_height = []
    peak_wave_period = []
    average_wave_height = []
    average_wave_period = []
    peak_wave_direction_puv = []
    peak_wave_spread_puv = []
    peak_wave_period_puv = []
    significant_wave_height_puv = []
    deployment = []
    sample_start_time = []

    # Number of iterations
    iters = 5

    # Remove edge effects
    edge = np.fix(1 * 30 * fs)

    for sample in np.unique(ds.sample):

        # Find the data associated with each sample
        index = np.where(ds.sample == sample)[0]

        # Get the start time
        tstart = ds.time[index].min().values

        # Get the deployment number
        dep_num = ds.deployment[index]

        # ----------------------------------------------------------------
        # Get the angular rates, accelerations, and compass data 
        # associated with the given sample data
        platform = Platform[:, index]
        deg_rate = Deg_rate[:, index]
        gyro = Compass[index]
        gravxyz = np.mean(platform.transpose(), axis=0) / G

        # Get the velocities and displacements
        uvw, xyz = uvw_xyz(gyro, platform, deg_rate, fs, f_cutoff, com_offset, G)

        # Remove the data at the beginning and end of the timeseries to 
        # reduce edge effects due to filtering
        incra = edge
        incrb = xyz.shape[-1] - edge
        incr = np.arange(incra, incrb+1, 1)
        incr = [int(x) for x in incr]

        # Calculate wave statistics from the zero-crossings
        z = xyz[2, :][incr]
        npt = np.min([2**13, len(incr)])
        Hsig, Havg, Tsig, Tavg = wave_statistics(z, fs, npt)

        # Calucate the wave spectra and the associated statistics
        vu = uvw[1, :][incr]
        vv = -uvw[0, :][incr]
        vp = z

        u_spectra, p_spectra, wave_direction, wave_spread, F, dF, dof = wave_spectra(vu, vv, vp, 1/fs, 100, 0, 0, params)
        Hm0, Fs, Tdir, Ts = wave_spectra_statistics(u_spectra, p_spectra, wave_direction, wave_spread, F, dF)

        # Save the results
        significant_wave_height.append(Hsig)    # Calculated from zero-crossings
        peak_wave_period.append(Tsig)           # Calculated from zero-crossings
        average_wave_height.append(Havg)        # Calculated from zero-crossings
        average_wave_period.append(Tavg)        # Calculated from zero-crossings
        peak_wave_direction_puv.append(Tdir)    # Calculated from the PUV method
        peak_wave_spread_puv.append(Ts)         # Calculated from the PUV method
        peak_wave_period_puv.append(1/Fs)       # Calculated from the PUV method
        significant_wave_height_puv.append(Hm0) # Calculated from the PUV method (Hm0)
        sample_start_time.append(tstart)

    # --------------------------------------------------------------------
    # Get the deployment number
    deployment = np.unique(ds.deployment)

    # --------------------------------------------------------------------
    # Build the wave statistics dataset
    wave_stats = build_dataset(ds, significant_wave_height, peak_wave_period, average_wave_height, average_wave_period,
                               peak_wave_direction_puv, peak_wave_spread_puv, peak_wave_period_puv, significant_wave_height_puv,
                               sample_start_time, deployment)
    
    return wave_stats