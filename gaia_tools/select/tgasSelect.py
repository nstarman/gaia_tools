###############################################################################
# tgasSelect.py: Selection function for (part of) the TGAS data set
###############################################################################
###############################################################################
#
# This file contains routines to compute the selection function of subsets
# of the Gaia DR1 TGAS data. As usual, care should be taken when using this
# set of tools for a subset for which the selection function has not been 
# previously tested.
#
# The basic, underlying, complete set of 2MASS counts was generated by the 
# following SQL query (applied using Python tools):
#
"""
select floor((j_m+(j_m-k_m)*(j_m-k_m)+2.5*(j_m-k_m))*10), \
floor((j_m-k_m+0.05)/1.05*3), floor(hp12index/16384), count(*) as count \
from twomass_psc, twomass_psc_hp12 \
where (twomass_psc.pts_key = twomass_psc_hp12.pts_key \
AND (ph_qual like 'A__' OR (rd_flg like '1__' OR rd_flg like '3__')) \
AND (ph_qual like '__A' OR (rd_flg like '__1' OR rd_flg like '__3')) \
AND use_src='1' AND ext_key is null \
AND (j_m-k_m) > -0.05 AND (j_m-k_m) < 1.0 AND j_m < 13.5 AND j_m > 2) \
group by floor((j_m+(j_m-k_m)*(j_m-k_m)+2.5*(j_m-k_m))*10), \
floor((j_m-k_m+0.05)/1.05*3),floor(hp12index/16384) \
order by floor((j_m+(j_m-k_m)*(j_m-k_m)+2.5*(j_m-k_m))*10) ASC;
"""
#
# and saved in 2massc_jk_jt_hp5_forsf.txt. The basic set of counts with 
# 6 < J < 10, 0.0 < J-Ks < 0.8 in HEALPix pixels was generated by the following
# SQL query
#
"""
select floor(hp12index/16384), count(*) as count \
from twomass_psc, twomass_psc_hp12 \
where (twomass_psc.pts_key = twomass_psc_hp12.pts_key \
AND (ph_qual like 'A__' OR (rd_flg like '1__' OR rd_flg like '3__')) \
AND (ph_qual like '__A' OR (rd_flg like '__1' OR rd_flg like '__3')) \
AND use_src='1' AND ext_key is null \
AND (j_m-k_m) > 0.0 AND (j_m-k_m) < 0.8 AND j_m > 6 AND j_m < 10) \
group by floor(hp12index/16384) \
order by floor(hp12index/16384) ASC;
"""
#
# and saved in 2massc_hp5.txt
###############################################################################
import os, os.path
import numpy
from scipy import interpolate
import astropy.coordinates as apco
import healpy
from galpy.util import bovy_plot
from matplotlib import cm
import gaia_tools.load
_BASE_NSIDE= 2**5
_BASE_NPIX= healpy.nside2npix(_BASE_NSIDE)
_SFFILES_DIR= os.path.dirname(os.path.realpath(__file__))
######################### Read file with counts in hp6 ########################
_2mc_skyonly= numpy.loadtxt(os.path.join(_SFFILES_DIR,'2massc_hp5.txt')).T
# Make sure all HEALPix pixels are available
ta= numpy.zeros((2,_BASE_NPIX))
ta[0][_2mc_skyonly[0].astype('int')]= _2mc_skyonly[0]
ta[1][_2mc_skyonly[0].astype('int')]= _2mc_skyonly[1]
_2mc_skyonly= ta
#################### Read file with counts in jt, j-k, hp5 ####################
_2mc= numpy.loadtxt(os.path.join(_SFFILES_DIR,'2massc_jk_jt_hp5_forsf.txt')).T
# Make value center of bin and re-normalize
_2mc[0]+= 0.5
_2mc[1]+= 0.5
_2mc[0]/= 10.
_2mc[1]= _2mc[1]*1.05/3.-0.05
class tgasSelect(object):
    def __init__(self,
                 min_nobs=8.5,
                 max_nobs_std=10.,
                 max_plxerr=1.01, # Effectively turns this off
                 max_scd=0.7,
                 min_lat=20.):
        """
        NAME:
           __init__
        PURPOSE:
           Initialize the TGAS selection function
        INPUT:
        OUTPUT:
           TGAS-selection-function object
        HISTORY:
           2017-01-17 - Started - Bovy (UofT/CCA)
        """
        # Load the data
        self._full_tgas= gaia_tools.load.tgas()
        self._full_twomass= gaia_tools.load.twomass(dr='tgas')
        self._full_jk= self._full_twomass['j_mag']-self._full_twomass['k_mag']
        self._full_jt= jt(self._full_jk,self._full_twomass['j_mag'])
        # Some overall statistics to aid in determining the good sky, setup 
        # related to statistics of 6 < J < 10
        self._setup_skyonly(min_nobs,max_nobs_std,max_plxerr,max_scd,min_lat)
        self._determine_selection()
        return None

    def _setup_skyonly(self,min_nobs,max_nobs_std,max_plxerr,max_scd,min_lat):
        self._tgas_sid= (self._full_tgas['source_id']/2**(35.\
                               +2*(12.-numpy.log2(_BASE_NSIDE)))).astype('int')
        self._tgas_sid_skyonlyindx= (self._full_jk > 0.)\
            *(self._full_jk < 0.8)\
            *(self._full_twomass['j_mag'] > 6.)\
            *(self._full_twomass['j_mag'] < 10.)
        nstar, e= numpy.histogram(self._tgas_sid[self._tgas_sid_skyonlyindx],
                                  range=[-0.5,_BASE_NPIX-0.5],bins=_BASE_NPIX)
        self._nstar_tgas_skyonly= nstar
        self._nobs_tgas_skyonly= self._compute_mean_quantity_tgas(\
            'astrometric_n_good_obs_al',lambda x: x/9.)
        self._nobsstd_tgas_skyonly= numpy.sqrt(\
            self._compute_mean_quantity_tgas(\
                'astrometric_n_good_obs_al',lambda x: (x/9.)**2.)
            -self._nobs_tgas_skyonly**2.)
        self._scank4_tgas_skyonly= self._compute_mean_quantity_tgas(\
            'scan_direction_strength_k4')
        self._plxerr_tgas_skyonly= self._compute_mean_quantity_tgas(\
            'parallax_error')
        tmp_decs, ras= healpy.pix2ang(_BASE_NSIDE,numpy.arange(_BASE_NPIX),
                                      nest=True)
        coos= apco.SkyCoord(ras,numpy.pi/2.-tmp_decs,unit="rad")
        coos= coos.transform_to(apco.GeocentricTrueEcliptic)
        self._eclat_skyonly= coos.lat.to('deg').value
        self._exclude_mask_skyonly= \
            (self._nobs_tgas_skyonly < min_nobs)\
            +(self._nobsstd_tgas_skyonly > max_nobs_std)\
            +(numpy.fabs(self._eclat_skyonly) < min_lat)\
            +(self._plxerr_tgas_skyonly > max_plxerr)\
            +(self._scank4_tgas_skyonly > max_scd)
        return None

    def _determine_selection(self):
        """Determine the Jt dependence of the selection function in the 'good'
        part of the sky"""
        jtbins= (numpy.amax(_2mc[0])-numpy.amin(_2mc[0]))/0.1+1
        nstar2mass, edges= numpy.histogramdd(\
            _2mc[:3].T,bins=[jtbins,3,_BASE_NPIX],
            range=[[numpy.amin(_2mc[0])-0.05,numpy.amax(_2mc[0])+0.05],
                   [-0.05,1.0],[-0.5,_BASE_NPIX-0.5]],weights=_2mc[3])
        findx= (self._full_jk > -0.05)*(self._full_jk < 1.0)\
            *(self._full_twomass['j_mag'] < 13.5)
        nstartgas, edges= numpy.histogramdd(\
            numpy.array([self._full_jt[findx],self._full_jk[findx],\
                             (self._full_tgas['source_id'][findx]\
                                  /2**(35.+2*(12.-numpy.log2(_BASE_NSIDE))))\
                             .astype('int')]).T,
            bins=[jtbins,3,_BASE_NPIX],
            range=[[numpy.amin(_2mc[0])-0.05,numpy.amax(_2mc[0])+0.05],
                   [-0.05,1.0],[-0.5,_BASE_NPIX-0.5]])
        # Only 'good' part of the sky
        nstar2mass[:,:,self._exclude_mask_skyonly]= numpy.nan
        nstartgas[:,:,self._exclude_mask_skyonly]= numpy.nan
        nstar2mass= numpy.nansum(nstar2mass,axis=-1)
        nstartgas= numpy.nansum(nstartgas,axis=-1)
        exs= 0.5*(numpy.roll(edges[0],1)+edges[0])[1:]
        # Three bins separate
        sf_splines= []
        sf_props= numpy.zeros((3,3))
        for ii in range(3):
            # Determine the plateau, out of interest
            level_indx= (exs > 8.5)*(exs < 9.5)
            sf_props[ii,0]=\
                numpy.nanmedian((nstartgas/nstar2mass)[level_indx,ii])
            # Spline interpolate
            spl_indx= (exs > 4.25)*(exs < 13.5)\
                *(True-numpy.isnan((nstartgas/nstar2mass)[:,ii]))
            tsf_spline= interpolate.UnivariateSpline(\
                exs[spl_indx],(nstartgas/nstar2mass)[spl_indx,ii],
                w=1./((numpy.sqrt(nstartgas)/nstar2mass)[spl_indx,ii]+0.02),
                k=3,ext=1,s=numpy.sum(spl_indx)/4.)
            # Determine where the sf hits 50% completeness 
            # at the bright and faint end
            bindx= spl_indx*(exs < 9.)
            xs= numpy.linspace(numpy.amin(exs[bindx]),numpy.amax(exs[bindx]),
                               1001)
            sf_props[ii,1]=\
                interpolate.InterpolatedUnivariateSpline(tsf_spline(xs),
                                                         xs,k=1)(0.5)
            # Faint
            findx= spl_indx*(exs > 9.)\
                *((nstartgas/nstar2mass)[:,ii]*sf_props[ii,0] < 0.8)
            xs= numpy.linspace(numpy.amin(exs[findx]),numpy.amax(exs[findx]),
                               1001)
            sf_props[ii,2]=\
                interpolate.InterpolatedUnivariateSpline(tsf_spline(xs)[::-1],
                                                         xs[::-1],k=1)(0.5)
            sf_splines.append(tsf_spline)
        self._sf_splines= sf_splines
        self._sf_props= sf_props
        return None

    def plot_mean_quantity_tgas(self,tag,func=None,**kwargs):
        """
        NAME:
           plot_mean_quantity_tgas
        PURPOSE:
           Plot the mean of a quantity in the TGAS catalog on the sky
        INPUT:
           tag - tag in the TGAS data to plot
           func= if set, a function to apply to the quantity
           +healpy.mollview plotting kwargs
        OUTPUT:
           plot to output device
        HISTORY:
           2017-01-17 - Written - Bovy (UofT/CCA)
        """
        mq= self._compute_mean_quantity_tgas(tag,func=func)
        cmap= cm.viridis
        cmap.set_under('w')
        kwargs['unit']= kwargs.get('unit',tag)
        kwargs['title']= kwargs.get('title',"")
        healpy.mollview(mq,nest=True,cmap=cmap,**kwargs)
        return None

    def _compute_mean_quantity_tgas(self,tag,func=None):
        """Function that computes the mean of a quantity in the TGAS catalog
        as a function of position on the sky, based on the sample with
        6 < J < 10 and 0 < J-Ks < 0.8"""
        if func is None: func= lambda x: x
        mq, e= numpy.histogram(self._tgas_sid[self._tgas_sid_skyonlyindx],
                               range=[-0.5,_BASE_NPIX-0.5],bins=_BASE_NPIX,
                               weights=func(self._full_tgas[tag]\
                                                [self._tgas_sid_skyonlyindx]))
        mq/= self._nstar_tgas_skyonly
        return mq
        
    def plot_2mass(self,jmin=None,jmax=None,
                   jkmin=None,jkmax=None,
                   cut=False,
                   **kwargs):
        """
        NAME:
           plot_2mass
        PURPOSE:
           Plot star counts in 2MASS
        INPUT:
           If the following are not set, fullsky will be plotted:
              jmin, jmax= minimum and maximum Jt
              jkmin, jkmax= minimum and maximum J-Ks
           cut= (False) if True, cut to the 'good' sky
           +healpy.mollview plotting kwargs
        OUTPUT:
           plot to output device
        HISTORY:
           2017-01-17 - Written - Bovy (UofT/CCA)
        """
        # Select stars
        if jmin is None or jmax is None \
                or jkmin is None or jkmax is None:
            pt= _2mc_skyonly[1]
        else:
            pindx= (_2mc[0] > jmin)*(_2mc[0] < jmax)\
                *(_2mc[1] > jkmin)*(_2mc[1] < jkmax)
            pt, e= numpy.histogram(_2mc[2][pindx],
                                   range=[-0.5,_BASE_NPIX-0.5],
                                   bins=_BASE_NPIX)
        pt= numpy.log10(pt)
        if cut: pt[self._exclude_mask_skyonly]= healpy.UNSEEN
        cmap= cm.viridis
        cmap.set_under('w')
        kwargs['unit']= r'$\log_{10}\mathrm{number\ counts}$'
        kwargs['title']= kwargs.get('title',"")
        healpy.mollview(pt,nest=True,cmap=cmap,**kwargs)
        return None

    def plot_tgas(self,jmin=None,jmax=None,
                  jkmin=None,jkmax=None,
                  cut=False,
                  **kwargs):
        """
        NAME:
           plot_tgas
        PURPOSE:
           Plot star counts in TGAS
        INPUT:
           If the following are not set, fullsky will be plotted:
              jmin, jmax= minimum and maximum Jt
              jkmin, jkmax= minimum and maximum J-Ks
           cut= (False) if True, cut to the 'good' sky
           +healpy.mollview plotting kwargs
        OUTPUT:
           plot to output device
        HISTORY:
           2017-01-17 - Written - Bovy (UofT/CCA)
        """
        # Select stars
        if jmin is None or jmax is None \
                or jkmin is None or jkmax is None:
            pt= self._nstar_tgas_skyonly
        else:
            pindx= (self._full_jt > jmin)*(self._full_jt < jmax)\
                *(self._full_jk > jkmin)*(self._full_jk < jkmax)
            pt, e= numpy.histogram((self._full_tgas['source_id']/2**(35.\
                      +2*(12.-numpy.log2(_BASE_NSIDE)))).astype('int')[pindx],
                                   range=[-0.5,_BASE_NPIX-0.5],
                                   bins=_BASE_NPIX)
        pt= numpy.log10(pt)
        if cut: pt[self._exclude_mask_skyonly]= healpy.UNSEEN
        cmap= cm.viridis
        cmap.set_under('w')
        kwargs['unit']= r'$\log_{10}\mathrm{number\ counts}$'
        kwargs['title']= kwargs.get('title',"")
        healpy.mollview(pt,nest=True,cmap=cmap,**kwargs)
        return None

    def plot_cmd(self,type='sf',cut=True):
        """
        NAME:
           plot_cmd
        PURPOSE:
           Plot the distribution of counts in the color-magnitude diagram
        INPUT:
           type= ('sf') Plot 'sf': selection function
                             'tgas': TGAS counts
                             '2mass': 2MASS counts
           cut= (True) cut to the 'good' part of the sky
        OUTPUT:
           Plot to output device
        HISTORY:
           2017-01-17 - Written - Bovy (UofT/CCA)
        """
        jtbins= (numpy.amax(_2mc[0])-numpy.amin(_2mc[0]))/0.1+1
        nstar2mass, edges= numpy.histogramdd(\
            _2mc[:3].T,bins=[jtbins,3,_BASE_NPIX],
            range=[[numpy.amin(_2mc[0])-0.05,numpy.amax(_2mc[0])+0.05],
                   [-0.05,1.0],[-0.5,_BASE_NPIX-0.5]],weights=_2mc[3])
        findx= (self._full_jk > -0.05)*(self._full_jk < 1.0)\
            *(self._full_twomass['j_mag'] < 13.5)
        nstartgas, edges= numpy.histogramdd(\
            numpy.array([self._full_jt[findx],self._full_jk[findx],\
                             (self._full_tgas['source_id'][findx]\
                                  /2**(35.+2*(12.-numpy.log2(_BASE_NSIDE))))\
                             .astype('int')]).T,
            bins=[jtbins,3,_BASE_NPIX],
            range=[[numpy.amin(_2mc[0])-0.05,numpy.amax(_2mc[0])+0.05],
                   [-0.05,1.0],[-0.5,_BASE_NPIX-0.5]])
        if cut:
            nstar2mass[:,:,self._exclude_mask_skyonly]= numpy.nan
            nstartgas[:,:,self._exclude_mask_skyonly]= numpy.nan
        nstar2mass= numpy.nansum(nstar2mass,axis=-1)
        nstartgas= numpy.nansum(nstartgas,axis=-1)
        if type == 'sf':
            pt= nstartgas/nstar2mass
            vmin= 0.
            vmax= 1.
            zlabel=r'$\mathrm{completeness}$'
        elif type == 'tgas' or type == '2mass':
            vmin= 0.
            vmax= 6.
            zlabel= r'$\log_{10}\mathrm{number\ counts}$'
            if type == 'tgas':
                pt= numpy.log10(nstartgas)
            elif type == '2mass':
                pt= numpy.log10(nstar2mass)
        return bovy_plot.bovy_dens2d(pt,origin='lower',
                                     cmap='viridis',interpolation='nearest',
                                     colorbar=True,shrink=0.78,
                                     vmin=vmin,vmax=vmax,zlabel=zlabel,
                                     yrange=[edges[0][0],edges[0][-1]],
                                     xrange=[edges[1][0],edges[1][-1]],
                                     xlabel=r'$J-K_s$',
                                     ylabel=r'$J+\Delta J$')
    def plot_magdist(self,type='sf',cut=True,splitcolors=False,overplot=False):
        """
        NAME:
           plot_magdist
        PURPOSE:
           Plot the distribution of counts in magnitude
        INPUT:
           type= ('sf') Plot 'sf': selection function
                             'tgas': TGAS counts
                             '2mass': 2MASS counts
           cut= (True) cut to the 'good' part of the sky
           splitcolors= (False) if True, plot the 3 color bins separately
        OUTPUT:
           Plot to output device
        HISTORY:
           2017-01-17 - Written - Bovy (UofT/CCA)
        """
        jtbins= (numpy.amax(_2mc[0])-numpy.amin(_2mc[0]))/0.1+1
        nstar2mass, edges= numpy.histogramdd(\
            _2mc[:3].T,bins=[jtbins,3,_BASE_NPIX],
            range=[[numpy.amin(_2mc[0])-0.05,numpy.amax(_2mc[0])+0.05],
                   [-0.05,1.0],[-0.5,_BASE_NPIX-0.5]],weights=_2mc[3])
        findx= (self._full_jk > -0.05)*(self._full_jk < 1.0)\
            *(self._full_twomass['j_mag'] < 13.5)
        nstartgas, edges= numpy.histogramdd(\
            numpy.array([self._full_jt[findx],self._full_jk[findx],\
                             (self._full_tgas['source_id'][findx]\
                                  /2**(35.+2*(12.-numpy.log2(_BASE_NSIDE))))\
                             .astype('int')]).T,
            bins=[jtbins,3,_BASE_NPIX],
            range=[[numpy.amin(_2mc[0])-0.05,numpy.amax(_2mc[0])+0.05],
                   [-0.05,1.0],[-0.5,_BASE_NPIX-0.5]])
        if cut:
            nstar2mass[:,:,self._exclude_mask_skyonly]= numpy.nan
            nstartgas[:,:,self._exclude_mask_skyonly]= numpy.nan
        nstar2mass= numpy.nansum(nstar2mass,axis=-1)
        nstartgas= numpy.nansum(nstartgas,axis=-1)
        exs= 0.5*(numpy.roll(edges[0],1)+edges[0])[1:]
        for ii in range(3):
            if type == 'sf':
                if splitcolors:
                    pt= nstartgas[:,ii]/nstar2mass[:,ii]
                else:
                    pt= numpy.nansum(nstartgas,axis=-1)\
                        /numpy.nansum(nstar2mass,axis=-1)
                vmin= 0.
                vmax= 1.
                ylabel=r'$\mathrm{completeness}$'
                semilogy= False
            elif type == 'tgas' or type == '2mass':
                vmin= 1.
                vmax= 10**6.
                ylabel= r'$\log_{10}\mathrm{number\ counts}$'
                semilogy= True
                if type == 'tgas':
                    if splitcolors:
                        pt= nstartgas[:,ii]
                    else:
                        pt= numpy.nansum(nstartgas,-1)
                elif type == '2mass':
                    if splitcolors:
                        pt= nstar2mass[:,ii]
                    else:
                        pt= numpy.nansum(nstar2mass,-1)
            bovy_plot.bovy_plot(exs,pt,ls='steps-mid',
                                xrange=[2.,14.],
                                yrange=[vmin,vmax],
                                semilogy=semilogy,
                                xlabel=r'$J+\Delta J$',
                                ylabel=ylabel,
                                overplot=(ii>0)+overplot)
            if not splitcolors: break
        return None

def jt(jk,j):
    return j+jk**2.+2.5*jk
