#  Migration script from Amazon Route53 to Linode DNS


# Installation

Download the script from Github and edit the settings at the top of the file

# Usage

    $ python route53_to_linode.py

# Instructions

By default the script will import all DNS zones it finds in Route53 for the given API key, the target domains
will be created in the Linode account associated with the API key given. The domains must not exist already or
the script will fail.

It is possible to import only selected Route53 zones into Linode by changing the IMPORT_ZONES setting, see the script
for further details.

# Requirements
You need to have a working python installation.

The script uses only standard libraries and a basic installation of any recent python version should work.
