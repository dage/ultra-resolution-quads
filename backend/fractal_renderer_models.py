import numpy as np
import numba
import fractalshades as fs
from fractalshades.postproc import Fractal_array
from typing import Optional, Union

class CustomFractal(fs.Fractal):
    """Base class for custom fractals to reduce boilerplate."""
    def __init__(self, directory):
        super().__init__(directory)
        self._numba_cache = {}
        self.potential_kind = "infinity"
        self.potential_d = 2
        self.potential_a_d = 1.
        self.potential_M_cutoff = 1000.
        self.holomorphic = True
        self.zn_iterate = None 

    def get_base_state_setter(self, complex_codes, int_codes, stop_codes, M_divergence):
        def set_state():
            def impl(instance):
                instance.codes = (complex_codes, int_codes, stop_codes)
                instance.complex_type = np.complex128
                instance.potential_M = M_divergence
            return impl
        return set_state

class Mandelbar(CustomFractal):
    """Tricorn / Mandelbar fractal: z = conj(z)^2 + c"""
    @fs.utils.calc_options
    def calc_std_div(self, *, calc_name="base_calc", subset=None, max_iter=10000, M_divergence=1000., epsilon_stationnary=0.01, calc_orbit=False, backshift=0):
        complex_codes = ["zn"]
        stop_codes = ["max_iter", "divergence", "stationnary"]
        zn = 0
        
        set_state = self.get_base_state_setter(complex_codes, [], stop_codes, M_divergence)

        def initialize():
            @numba.njit
            def numba_impl(Z, U, c):
                Z[zn] = 0.0
            return numba_impl

        Mdiv_sq = M_divergence ** 2

        def iterate():
            @numba.njit
            def numba_impl(c, Z, U, stop_reason):
                n_iter = 0
                while n_iter < max_iter:
                    # Mandelbar: z = conj(z)^2 + c
                    z = Z[zn]
                    z_conj = z.real - 1j * z.imag
                    Z[zn] = z_conj * z_conj + c

                    if Z[zn].real ** 2 + Z[zn].imag ** 2 > Mdiv_sq:
                        stop_reason[0] = 1
                        return n_iter
                    
                    n_iter += 1
                
                stop_reason[0] = 0
                return n_iter
            return numba_impl

        return {"set_state": set_state, "initialize": initialize, "iterate": iterate}

class PBS(CustomFractal):
    """Perpendicular Burning Ship: z = (Re(z) + i|Im(z)|)^2 + c"""
    @fs.utils.calc_options
    def calc_std_div(self, *, calc_name="base_calc", subset=None, max_iter=10000, M_divergence=1000., epsilon_stationnary=0.01, calc_orbit=False, backshift=0):
        complex_codes = ["zn"]
        stop_codes = ["max_iter", "divergence"]
        zn = 0
        
        set_state = self.get_base_state_setter(complex_codes, [], stop_codes, M_divergence)

        def initialize():
            @numba.njit
            def numba_impl(Z, U, c):
                Z[zn] = 0.0
            return numba_impl

        Mdiv_sq = M_divergence ** 2

        def iterate():
            @numba.njit
            def numba_impl(c, Z, U, stop_reason):
                n_iter = 0
                while n_iter < max_iter:
                    z = Z[zn]
                    # PBS: Re(z) + i|Im(z)|
                    # Manual abs
                    im_z = z.imag
                    if im_z < 0:
                        im_z = -im_z
                    
                    val = z.real + 1j * im_z
                    Z[zn] = val * val + c

                    if Z[zn].real ** 2 + Z[zn].imag ** 2 > Mdiv_sq:
                        stop_reason[0] = 1
                        return n_iter
                    n_iter += 1

                stop_reason[0] = 0
                return n_iter
            return numba_impl

        return {"set_state": set_state, "initialize": initialize, "iterate": iterate}

class Celtic(CustomFractal):
    """Celtic Mandelbrot: z = |Re(z^2)| + i Im(z^2) + c"""
    @fs.utils.calc_options
    def calc_std_div(self, *, calc_name="base_calc", subset=None, max_iter=10000, M_divergence=1000., epsilon_stationnary=0.01, calc_orbit=False, backshift=0):
        complex_codes = ["zn"]
        stop_codes = ["max_iter", "divergence"]
        zn = 0
        
        set_state = self.get_base_state_setter(complex_codes, [], stop_codes, M_divergence)

        def initialize():
            @numba.njit
            def numba_impl(Z, U, c):
                Z[zn] = 0.0
            return numba_impl

        Mdiv_sq = M_divergence ** 2

        def iterate():
            @numba.njit
            def numba_impl(c, Z, U, stop_reason):
                n_iter = 0
                while n_iter < max_iter:
                    z = Z[zn]
                    z2 = z * z
                    # Celtic: |Re(z^2)| + i Im(z^2)
                    # Manual abs
                    re_z2 = z2.real
                    if re_z2 < 0:
                        re_z2 = -re_z2
                        
                    Z[zn] = re_z2 + 1j * z2.imag + c

                    if Z[zn].real ** 2 + Z[zn].imag ** 2 > Mdiv_sq:
                        stop_reason[0] = 1
                        return n_iter
                    n_iter += 1
                
                stop_reason[0] = 0
                return n_iter
            return numba_impl

        return {"set_state": set_state, "initialize": initialize, "iterate": iterate}

class Julia(CustomFractal):
    """Julia Set (z^2+c) where c is constant and z0 is pixel."""
    def __init__(self, directory, c_val):
        super().__init__(directory)
        self.c_val = c_val
        
        c_const = self.c_val
        @numba.njit
        def julia_iterate(zn, c_pix):
            return zn * zn + c_const
        self.zn_iterate = julia_iterate

    @fs.utils.calc_options
    def calc_std_div(self, *, calc_name="base_calc", subset=None, max_iter=10000, M_divergence=1000., epsilon_stationnary=0.01, calc_orbit=False, backshift=0):
        complex_codes = ["zn"]
        stop_codes = ["max_iter", "divergence"]
        zn = 0
        
        set_state = self.get_base_state_setter(complex_codes, [], stop_codes, M_divergence)

        def initialize():
            @numba.njit
            def numba_impl(Z, U, c):
                # For Julia, init Z with pixel coordinate c
                Z[zn] = c
            return numba_impl

        Mdiv_sq = M_divergence ** 2
        c_const = self.c_val

        def iterate():
            @numba.njit
            def numba_impl(c, Z, U, stop_reason):
                n_iter = 0
                while n_iter < max_iter:
                    Z[zn] = Z[zn] ** 2 + c_const

                    if Z[zn].real ** 2 + Z[zn].imag ** 2 > Mdiv_sq:
                        stop_reason[0] = 1
                        return n_iter
                    n_iter += 1
                
                stop_reason[0] = 0
                return n_iter
            return numba_impl

        return {"set_state": set_state, "initialize": initialize, "iterate": iterate}

class Nova(CustomFractal):
    """Nova: z = z - (z^p - 1)/(p*z^(p-1)) + c. p=3 default."""
    def __init__(self, directory, p=3):
        super().__init__(directory)
        self.p = float(p)
        self.potential_d = float(p)

    @fs.utils.calc_options
    def calc_std_div(self, *, calc_name="base_calc", subset=None, max_iter=10000, M_divergence=1000., epsilon_stationnary=0.01, calc_orbit=False, backshift=0):
        complex_codes = ["zn"]
        stop_codes = ["max_iter", "divergence"]
        zn = 0
        
        set_state = self.get_base_state_setter(complex_codes, [], stop_codes, M_divergence)
        
        p_val = self.p

        def initialize():
            @numba.njit
            def numba_impl(Z, U, c):
                Z[zn] = 1.0 
            return numba_impl

        Mdiv_sq = M_divergence ** 2
        
        def iterate():
            @numba.njit
            def numba_impl(c, Z, U, stop_reason):
                n_iter = 0
                while n_iter < max_iter:
                    z = Z[zn]
                    if z == 0:
                        z = 1e-10 
                    
                    term = (z**p_val - 1.0) / (p_val * z**(p_val - 1.0))
                    Z[zn] = z - term + c

                    if np.abs(term) < 0.001: # converged
                        stop_reason[0] = 1 
                        return n_iter
                    
                    n_iter += 1
                
                stop_reason[0] = 0
                return n_iter
            return numba_impl

        return {"set_state": set_state, "initialize": initialize, "iterate": iterate}

class Phoenix(CustomFractal):
    """Phoenix: z_{n+1} = z_n^2 + c + p * z_{n-1}. Note: 'c' is pixel, 'p' is constant."""
    def __init__(self, directory, p_param=(-0.5, 0.0)):
        super().__init__(directory)
        self.p_param = p_param[0] + 1j * p_param[1]

    @fs.utils.calc_options
    def calc_std_div(self, *, calc_name="base_calc", subset=None, max_iter=10000, M_divergence=1000., epsilon_stationnary=0.01, calc_orbit=False, backshift=0):
        complex_codes = ["zn", "zn_1"]
        stop_codes = ["max_iter", "divergence"]
        zn = 0
        zn_1 = 1
        
        set_state = self.get_base_state_setter(complex_codes, [], stop_codes, M_divergence)
        
        p_const = self.p_param

        def initialize():
            @numba.njit
            def numba_impl(Z, U, c):
                Z[zn] = 0.0 
                Z[zn_1] = 0.0
            return numba_impl

        Mdiv_sq = M_divergence ** 2

        def iterate():
            @numba.njit
            def numba_impl(c, Z, U, stop_reason):
                n_iter = 0
                while n_iter < max_iter:
                    z = Z[zn]
                    z_prev = Z[zn_1]
                    
                    z_new = z*z + c + p_const * z_prev
                    
                    Z[zn_1] = z
                    Z[zn] = z_new

                    if Z[zn].real ** 2 + Z[zn].imag ** 2 > Mdiv_sq:
                        stop_reason[0] = 1
                        return n_iter
                    n_iter += 1
                
                stop_reason[0] = 0
                return n_iter
            return numba_impl

        return {"set_state": set_state, "initialize": initialize, "iterate": iterate}
