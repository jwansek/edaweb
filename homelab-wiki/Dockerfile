FROM mediawiki:1.43.3

ENV MW_HOME=/var/www/html

# download and add composer to path
RUN set -x; \
    php -r "readfile('https://getcomposer.org/installer');" | php \
    && mv composer.phar /usr/local/bin/composer

# get extensions
RUN set -x; \
    cd $MW_HOME/extensions \
    && git clone --depth 1 -b REL1_39 https://github.com/wikimedia/mediawiki-extensions-TemplateStyles \ 
    && git clone --depth 1 https://github.com/Universal-Omega/PortableInfobox.git

# install extensions
RUN set -x; \
    cd $MW_HOME/extensions/mediawiki-extensions-TemplateStyles \
    && composer install --no-dev
