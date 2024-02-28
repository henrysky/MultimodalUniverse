import os
import argparse
from astropy.table import Table, vstack, join
from tqdm import tqdm
import glob
import h5py
import healpy as hp
import numpy as np
from multiprocessing import Pool

CATALOG_COLUMNS = [
    'inds',
    'ra',
    'dec',
    'release',
    'brickid',
    'objid',
    'z_spec',
    'flux',
    'flux_ivar',
    'psfsize',
    'ebv'
]

_image_size = 152
_pixel_scale = 0.262


def _processing_fn(args):
    catalog, input_files, output_filename = args

    if not os.path.exists(os.path.dirname(output_filename)):
        os.makedirs(os.path.dirname(output_filename))

    keys = catalog['inds']

    # Preparing an index for fast searching through the catalog
    sort_index = np.argsort(catalog['inds'])
    sorted_ids = catalog['inds'][sort_index]

    # Open all the data files
    files = [h5py.File(file, 'r') for file in input_files]

    images = []
    indss = []
    psf_sizes = []
    # Loop over the indices and yield the requested data
    for i, id in enumerate(keys):
        # Extract the indices of requested ids in the catalog 
        idx = sort_index[np.searchsorted(sorted_ids, id)]
        row = catalog[idx]

        # Get the entry from the corresponding file
        file_idx = id // 1_000_000
        file_ind = id % 1_000_000

        images.append(files[file_idx]['images'][file_ind])
        indss.append(files[file_idx]['inds'][file_ind])

    # Stack the images and indices, and create an astropy table
    images = np.stack(images, axis=0)
    indss = np.stack(indss, axis=0)
    image_cat = Table({'inds': indss, 'images': images})

    # Close all the data files
    for file in files:
        file.close()
    
    # Making sure we foynf the right number of images
    assert len(catalog) == len(images), "There was an error retrieving images"
    # Join on inds with the input catalog
    catalog = join(catalog, image_cat, keys='inds', join_type='inner')
    # Making sure we didn't lose anyone
    assert len(catalog) == len(images), "There was an error in the join operation"
    
    # Save all columns to disk in HDF5 format
    with h5py.File(output_filename, 'w') as hdf5_file:
        for key in catalog.colnames:
            hdf5_file.create_dataset(key, data=catalog[key])

    return 1

def save_in_standard_format(catalog_filename, sample_name, data_path, output_dir, num_processes=None):
    """ This function takes care of saving the dataset in the standard format used by the rest of the project
    """
    # Load the catalog
    catalog = Table.read(catalog_filename)
    
    # Group objects by healpix index
    groups = catalog.group_by('healpix')

    # Loop over the groups
    map_args = []
    input_files = glob.glob(data_path+f'{sample_name}/images_npix152*.h5')
    for group in groups.groups:
        # Create a filename for the group
        group_filename = os.path.join(output_dir, '{}/healpix={}/001-of-001.hdf5'.format(sample_name,group['healpix'][0]))
        map_args.append((group, input_files, group_filename))

    print('Exporting aggregated dataset in hdf5 format to disk...')

    # Run the parallel processing
    with Pool(num_processes) as pool:
        results = list(tqdm(pool.imap(_processing_fn, map_args), total=len(map_args)))

    if np.sum(results) == len(groups.groups):
        print('Done!')
    else:
        print("Warning, unexpected number of results, some files may not have been exported as expected")


def main(args):
    # Looping over the downloaded image files to retrieve important catalog information
    catalogs = []
    for file in tqdm(glob.glob(args.data_path+'north/images_npix152*.h5')):
        with h5py.File(file) as d:
            catalogs.append(Table(data=[d[k][:] for k in CATALOG_COLUMNS], 
                                  names=CATALOG_COLUMNS))
    catalog = vstack(catalogs, join_type='exact')
    # Making sure the catalog is sorted by inds in ascending order
    catalog.sort('inds')
    # Add healpix index to the catalog
    catalog['healpix'] = hp.ang2pix(64, catalog['ra'], catalog['dec'], lonlat=True, nest=True)
    # Save the catalog
    catalog_filename = os.path.join(args.output_dir, 'decals_catalog_north.fits')
    catalog.write(catalog_filename, overwrite=True)

    # Next step, export the data into the standard format
    save_in_standard_format(catalog_filename, 'north', args.output_dir, num_processes=args.num_processes)

    # Now doing the same thing for the south sample
    catalogs = []
    for file in tqdm(glob.glob(args.data_path+'south/images_npix152*.h5')):
        with h5py.File(file) as d:
            catalogs.append(Table(data=[d[k][:] for k in CATALOG_COLUMNS], 
                                  names=CATALOG_COLUMNS))
    catalog = vstack(catalogs, join_type='exact')
    # Making sure the catalog is sorted by inds in ascending order
    catalog.sort('inds')
    # Add healpix index to the catalog
    catalog['healpix'] = hp.ang2pix(64, catalog['ra'], catalog['dec'], lonlat=True, nest=True)
    # Save the catalog
    catalog_filename = os.path.join(args.output_dir, 'decals_catalog_south.fits')
    catalog.write(catalog_filename, overwrite=True)

    # Next step, export the data into the standard format
    save_in_standard_format(catalog_filename, 'south', args.output_dir, num_processes=args.num_processes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Builds a catalog for the DECALS images of the stein et al. sample')
    parser.add_argument('data_path', type=str, help='Path to the local copy of the data')
    parser.add_argument('output_dir', type=str, help='Path to the output directory')
    parser.add_argument('--num_processes', type=int, default=1, help='Number of parallel processes to use')
    args = parser.parse_args()

    main(args)